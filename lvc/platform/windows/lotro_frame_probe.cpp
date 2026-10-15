// One explicitly selected LOTRO HWND frame to stdout, never a desktop capture.
// Windows.Graphics.Capture interop follows Microsoft's MIT-licensed
// ScreenCaptureforHWND sample. Raw pixels stay in process memory/pipe only.
#include <windows.h>
#include <d3d11.h>
#include <dxgi1_2.h>
#include <windows.graphics.capture.interop.h>
#include <windows.graphics.directx.direct3d11.interop.h>
#include <winrt/base.h>
#include <winrt/Windows.Foundation.h>
#include <winrt/Windows.Graphics.Capture.h>
#include <winrt/Windows.Graphics.DirectX.h>
#include <winrt/Windows.Graphics.DirectX.Direct3D11.h>

#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <iostream>
#include <io.h>
#include <string>
#include <vector>

#pragma comment(lib, "d3d11.lib")
#pragma comment(lib, "user32.lib")
#pragma comment(lib, "windowsapp.lib")

using namespace winrt;
using namespace winrt::Windows::Graphics::Capture;
using namespace winrt::Windows::Graphics::DirectX;
using namespace winrt::Windows::Graphics::DirectX::Direct3D11;

struct Identity {
    HWND hwnd{};
    DWORD pid{};
    uint64_t started{};
    std::wstring path;
};

uint64_t ticks(FILETIME value) {
    ULARGE_INTEGER number{};
    number.LowPart = value.dwLowDateTime;
    number.HighPart = value.dwHighDateTime;
    return number.QuadPart;
}

bool eligible_name(std::wstring const& path) {
    auto slash = path.find_last_of(L"\\/");
    auto name = path.substr(slash == std::wstring::npos ? 0 : slash + 1);
    return _wcsicmp(name.c_str(), L"lotroclient64.exe") == 0;
}

bool inspect(HWND hwnd, Identity& result) {
    if (!IsWindow(hwnd) || !IsWindowVisible(hwnd) || IsIconic(hwnd) ||
        GetAncestor(hwnd, GA_ROOT) != hwnd) return false;
    RECT client{};
    if (!GetClientRect(hwnd, &client) || client.right <= client.left ||
        client.bottom <= client.top) return false;
    DWORD pid = 0;
    if (!GetWindowThreadProcessId(hwnd, &pid) || !pid) return false;
    HANDLE process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid);
    if (!process) return false;
    FILETIME created{}, exited{}, kernel{}, user{};
    wchar_t path[32768]{};
    DWORD size = 32768;
    bool okay = GetProcessTimes(process, &created, &exited, &kernel, &user) &&
                QueryFullProcessImageNameW(process, 0, path, &size);
    CloseHandle(process);
    if (!okay || !size) return false;
    result = {hwnd, pid, ticks(created), std::wstring(path, size)};
    return eligible_name(result.path);
}

bool current(Identity const& expected, bool require_foreground) {
    Identity actual{};
    return inspect(expected.hwnd, actual) && actual.pid == expected.pid &&
           actual.started == expected.started &&
           _wcsicmp(actual.path.c_str(), expected.path.c_str()) == 0 &&
           (!require_foreground || GetForegroundWindow() == expected.hwnd);
}

bool parse_u64(wchar_t const* source, uint64_t& output) {
    if (!source || !*source || *source == L'-') return false;
    wchar_t* end = nullptr;
    unsigned long long value = wcstoull(source, &end, 10);
    if (!end || *end || end == source) return false;
    output = static_cast<uint64_t>(value);
    return true;
}

struct FrameResult {
    std::atomic<bool> finished{false};
    std::vector<uint8_t> rgb;
    uint32_t width{};
    uint32_t height{};
};

void accept_frame(Direct3D11CaptureFramePool const& pool,
                  Identity const& selected, com_ptr<ID3D11Device> const& device,
                  FrameResult& result) {
    if (result.finished.load()) return;
    try {
        auto frame = pool.TryGetNextFrame();
        if (!frame || !current(selected, true)) {
            result.finished = true;
            return;
        }
        auto content = frame.ContentSize();
        if (content.Width <= 0 || content.Height <= 0 ||
            content.Width > 8192 || content.Height > 8192 ||
            static_cast<uint64_t>(content.Width) * content.Height > 32'000'000)
            throw hresult_error(E_INVALIDARG);
        auto access = frame.Surface().as<::Windows::Graphics::DirectX::Direct3D11::IDirect3DDxgiInterfaceAccess>();
        com_ptr<ID3D11Texture2D> texture;
        check_hresult(access->GetInterface(guid_of<ID3D11Texture2D>(), texture.put_void()));
        D3D11_TEXTURE2D_DESC desc{};
        texture->GetDesc(&desc);
        if (desc.Format != DXGI_FORMAT_B8G8R8A8_UNORM ||
            static_cast<uint32_t>(content.Width) > desc.Width ||
            static_cast<uint32_t>(content.Height) > desc.Height)
            throw hresult_error(E_INVALIDARG);
        D3D11_TEXTURE2D_DESC staging_desc = desc;
        staging_desc.Usage = D3D11_USAGE_STAGING;
        staging_desc.BindFlags = 0;
        staging_desc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
        staging_desc.MiscFlags = 0;
        com_ptr<ID3D11Texture2D> staging;
        check_hresult(device->CreateTexture2D(&staging_desc, nullptr, staging.put()));
        com_ptr<ID3D11DeviceContext> context;
        device->GetImmediateContext(context.put());
        context->CopyResource(staging.get(), texture.get());
        D3D11_MAPPED_SUBRESOURCE mapped{};
        check_hresult(context->Map(staging.get(), 0, D3D11_MAP_READ, 0, &mapped));
        std::vector<uint8_t> rgb(static_cast<size_t>(content.Width) * content.Height * 3);
        for (int y = 0; y < content.Height; ++y) {
            auto row = static_cast<uint8_t const*>(mapped.pData) +
                       static_cast<size_t>(y) * mapped.RowPitch;
            for (int x = 0; x < content.Width; ++x) {
                size_t target = (static_cast<size_t>(y) * content.Width + x) * 3;
                size_t source = static_cast<size_t>(x) * 4;
                rgb[target] = row[source + 2];
                rgb[target + 1] = row[source + 1];
                rgb[target + 2] = row[source];
            }
        }
        context->Unmap(staging.get(), 0);
        if (!current(selected, true)) {
            result.finished = true;
            return;
        }
        result.width = static_cast<uint32_t>(content.Width);
        result.height = static_cast<uint32_t>(content.Height);
        result.rgb = std::move(rgb);
        result.finished = true;
    } catch (...) {
        result.finished = true;
    }
}

int fail(char const* reason) {
    std::cerr << "BLOCKED:" << reason << '\n';
    return 2;
}

int wmain(int argc, wchar_t** argv) {
    if (argc != 6 || wcscmp(argv[1], L"--explicit-lotro-window") != 0)
        return fail("EXPLICIT_SELECTION_ARGUMENTS_REQUIRED");
    uint64_t raw_hwnd = 0, raw_pid = 0, raw_started = 0;
    if (!parse_u64(argv[2], raw_hwnd) || !parse_u64(argv[3], raw_pid) ||
        !parse_u64(argv[4], raw_started) || !raw_hwnd || !raw_pid ||
        raw_pid > UINT32_MAX || !raw_started)
        return fail("INVALID_NATIVE_IDENTITY_ARGUMENTS");
    Identity selected{reinterpret_cast<HWND>(static_cast<uintptr_t>(raw_hwnd)),
                      static_cast<DWORD>(raw_pid), raw_started, argv[5]};
    if (!eligible_name(selected.path) || !current(selected, false))
        return fail("SELECTED_WINDOW_IDENTITY_CHANGED");
    try {
        init_apartment(apartment_type::multi_threaded);
        if (!GraphicsCaptureSession::IsSupported()) return fail("WGC_UNSUPPORTED");
        // The user returns to the selected game after launching the probe.
        const DWORD focus_start = GetTickCount();
        while (GetForegroundWindow() != selected.hwnd &&
               GetTickCount() - focus_start < 8000) {
            if (!current(selected, false)) return fail("WINDOW_CHANGED_DURING_FOCUS_WAIT");
            Sleep(20);
        }
        if (!current(selected, true)) return fail("SELECTED_WINDOW_NOT_FOREGROUND");
        com_ptr<ID3D11Device> d3d;
        check_hresult(D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr,
                                        D3D11_CREATE_DEVICE_BGRA_SUPPORT, nullptr, 0,
                                        D3D11_SDK_VERSION, d3d.put(), nullptr, nullptr));
        auto dxgi = d3d.as<IDXGIDevice>();
        com_ptr<::IInspectable> inspectable;
        check_hresult(CreateDirect3D11DeviceFromDXGIDevice(dxgi.get(), inspectable.put()));
        auto device = inspectable.as<IDirect3DDevice>();
        auto activation = get_activation_factory<GraphicsCaptureItem>();
        auto interop = activation.as<IGraphicsCaptureItemInterop>();
        GraphicsCaptureItem item{nullptr};
        check_hresult(interop->CreateForWindow(
            selected.hwnd,
            guid_of<ABI::Windows::Graphics::Capture::IGraphicsCaptureItem>(),
            reinterpret_cast<void**>(put_abi(item))));
        if (!current(selected, true)) return fail("WINDOW_CHANGED_BEFORE_CAPTURE");
        auto pool = Direct3D11CaptureFramePool::CreateFreeThreaded(
            device, DirectXPixelFormat::B8G8R8A8UIntNormalized, 2, item.Size());
        auto session = pool.CreateCaptureSession(item);
        FrameResult frame;
        auto token = pool.FrameArrived([&](auto const& sender, auto const&) {
            accept_frame(sender, selected, d3d, frame);
        });
        session.StartCapture();
        const DWORD start = GetTickCount();
        while (!frame.finished && GetTickCount() - start < 3000) {
            if (!current(selected, true)) break;
            Sleep(10);
        }
        pool.FrameArrived(token);
        session.Close();
        pool.Close();
        if (!frame.finished || frame.rgb.empty() || !current(selected, true))
            return fail("NO_CURRENT_FRAME");
        if (_setmode(_fileno(stdout), _O_BINARY) < 0) return fail("BINARY_PIPE_UNAVAILABLE");
        uint32_t header[2]{frame.width, frame.height};
        std::cout.write("LVCF", 4);
        std::cout.write(reinterpret_cast<char const*>(header), sizeof(header));
        std::cout.write(reinterpret_cast<char const*>(frame.rgb.data()),
                        static_cast<std::streamsize>(frame.rgb.size()));
        std::cout.flush();
        return std::cout.good() ? 0 : fail("FRAME_PIPE_WRITE_FAILED");
    } catch (hresult_error const& error) {
        std::cerr << "BLOCKED:WGC_HRESULT_" << std::hex
                  << static_cast<uint32_t>(error.code().value) << '\n';
        return 2;
    }
}
