// Local Windows OCR helper for the manual, single-frame preview.
// Reads one bounded PNG from stdin and returns only UTF-8 OCR text on stdout.
#include <fcntl.h>
#include <io.h>
#include <windows.h>
#include <winrt/base.h>
#include <winrt/Windows.Foundation.h>
#include <winrt/Windows.Foundation.Collections.h>
#include <winrt/Windows.Globalization.h>
#include <winrt/Windows.Graphics.Imaging.h>
#include <winrt/Windows.Media.Ocr.h>
#include <winrt/Windows.Storage.Streams.h>

#include <iostream>
#include <iterator>
#include <string>
#include <vector>

#pragma comment(lib, "windowsapp.lib")

namespace {
constexpr size_t max_png_bytes = 8 * 1024 * 1024;
constexpr size_t max_text_bytes = 256 * 1024;

std::string utf8(winrt::hstring const& value) {
    auto const* raw = value.c_str();
    int count = WideCharToMultiByte(CP_UTF8, 0, raw, static_cast<int>(value.size()),
                                    nullptr, 0, nullptr, nullptr);
    std::string result(static_cast<size_t>(count), '\0');
    WideCharToMultiByte(CP_UTF8, 0, raw, static_cast<int>(value.size()),
                        result.data(), count, nullptr, nullptr);
    return result;
}
}  // namespace

int main() {
    _setmode(_fileno(stdin), _O_BINARY);
    _setmode(_fileno(stdout), _O_BINARY);
    std::vector<uint8_t> png;
    char chunk[8192];
    while (std::cin) {
        std::cin.read(chunk, sizeof(chunk));
        auto count = std::cin.gcount();
        if (count > 0) {
            if (png.size() + static_cast<size_t>(count) > max_png_bytes) {
                std::cerr << "INPUT_TOO_LARGE\n";
                return 2;
            }
            png.insert(png.end(), chunk, chunk + count);
        }
    }
    if (png.empty()) {
        std::cerr << "EMPTY_INPUT\n";
        return 2;
    }
    try {
        winrt::init_apartment(winrt::apartment_type::multi_threaded);
        using namespace winrt::Windows;
        auto engine = Media::Ocr::OcrEngine::TryCreateFromLanguage(
            Globalization::Language(L"en-US"));
        if (!engine) {
            std::cerr << "ENGLISH_OCR_UNAVAILABLE\n";
            return 3;
        }
        auto stream = Storage::Streams::InMemoryRandomAccessStream();
        auto writer = Storage::Streams::DataWriter(stream.GetOutputStreamAt(0));
        writer.WriteBytes(png);
        writer.StoreAsync().get();
        writer.FlushAsync().get();
        stream.Seek(0);
        auto decoder = Graphics::Imaging::BitmapDecoder::CreateAsync(stream).get();
        auto bitmap = decoder.GetSoftwareBitmapAsync().get();
        if (bitmap.BitmapPixelFormat() != Graphics::Imaging::BitmapPixelFormat::Gray8 &&
            bitmap.BitmapPixelFormat() != Graphics::Imaging::BitmapPixelFormat::Bgra8) {
            bitmap = Graphics::Imaging::SoftwareBitmap::Convert(
                bitmap, Graphics::Imaging::BitmapPixelFormat::Bgra8);
        }
        auto result = engine.RecognizeAsync(bitmap).get();
        auto output = utf8(result.Text());
        if (output.size() > max_text_bytes) {
            std::cerr << "OUTPUT_TOO_LARGE\n";
            return 4;
        }
        std::cout.write(output.data(), static_cast<std::streamsize>(output.size()));
        return 0;
    } catch (winrt::hresult_error const& error) {
        std::cerr << "WINDOWS_OCR_ERROR " << std::hex << error.code().value << "\n";
        return 5;
    } catch (std::exception const&) {
        std::cerr << "WINDOWS_OCR_ERROR\n";
        return 5;
    }
}
