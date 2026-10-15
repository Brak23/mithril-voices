// One bounded, application-owned HWND capture probe. No arbitrary HWND input.
// The CreateForWindow and D3D interop pattern follows Microsoft's MIT-licensed
// ScreenCaptureforHWND sample; this probe is original and retains no pixels.
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
#include <iostream>
#include <string>

#pragma comment(lib, "d3d11.lib")
#pragma comment(lib, "gdi32.lib")
#pragma comment(lib, "user32.lib")
#pragma comment(lib, "windowsapp.lib")

using namespace winrt;
using namespace winrt::Windows::Graphics::Capture;
using namespace winrt::Windows::Graphics::DirectX;
using namespace winrt::Windows::Graphics::DirectX::Direct3D11;

struct WindowIdentity {
    HWND hwnd{};
    DWORD pid{};
    uint64_t started{};
    std::wstring path;
};

thread_local int inspection_failure = 0;

uint64_t filetime_ticks(FILETIME value) {
    ULARGE_INTEGER bits{};
    bits.LowPart = value.dwLowDateTime;
    bits.HighPart = value.dwHighDateTime;
    return bits.QuadPart;
}

bool inspect_window(HWND hwnd, WindowIdentity& result) {
    inspection_failure = 0;
    if (!IsWindow(hwnd)) { inspection_failure = 1; return false; }
    if (!IsWindowVisible(hwnd)) { inspection_failure = 2; return false; }
    if (IsIconic(hwnd)) { inspection_failure = 3; return false; }
    RECT client{};
    if (!GetClientRect(hwnd, &client) || client.right <= client.left ||
        client.bottom <= client.top) { inspection_failure = 4; return false; }
    DWORD pid = 0;
    if (!GetWindowThreadProcessId(hwnd, &pid) || pid == 0) {
        inspection_failure = 5; return false;
    }
    const bool owned_process = pid == GetCurrentProcessId();
    HANDLE process = owned_process ? GetCurrentProcess()
                                   : OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid);
    if (!process) { inspection_failure = 6; return false; }
    FILETIME created{}, exited{}, kernel{}, user{};
    wchar_t path[32768]{};
    DWORD path_size = 32768;
    const bool times_okay = GetProcessTimes(process, &created, &exited, &kernel, &user);
    const bool path_okay = times_okay && QueryFullProcessImageNameW(process, 0, path, &path_size);
    if (!owned_process) CloseHandle(process);
    if (!times_okay) { inspection_failure = 7; return false; }
    if (!path_okay || !path_size) { inspection_failure = 8; return false; }
    result = {hwnd, pid, filetime_ticks(created), std::wstring(path, path_size)};
    return true;
}

bool same_window(HWND hwnd, WindowIdentity const& selected) {
    WindowIdentity current{};
    return inspect_window(hwnd, current) && current.hwnd == selected.hwnd &&
           current.pid == selected.pid && current.started == selected.started &&
           _wcsicmp(current.path.c_str(), selected.path.c_str()) == 0;
}

LRESULT CALLBACK fixture_proc(HWND hwnd, UINT message, WPARAM wparam, LPARAM lparam) {
    if (message == WM_PAINT) {
        PAINTSTRUCT paint{};
        HDC dc = BeginPaint(hwnd, &paint);
        RECT client{};
        GetClientRect(hwnd, &client);
        FillRect(dc, &client, reinterpret_cast<HBRUSH>(GetStockObject(WHITE_BRUSH)));
        RECT marker{50, 50, 100, 100};
        HBRUSH magenta = CreateSolidBrush(RGB(255, 0, 255));
        FillRect(dc, &marker, magenta);
        DeleteObject(magenta);
        SetBkMode(dc, TRANSPARENT);
        SetTextColor(dc, RGB(0, 0, 0));
        TextOutW(dc, 30, 130, L"Bring 10 stones, not 18.", 24);
        EndPaint(hwnd, &paint);
        return 0;
    }
    return DefWindowProcW(hwnd, message, wparam, lparam);
}

struct Metrics {
    std::atomic<bool> done{false};
    std::atomic<bool> accepted{false};
    std::atomic<bool> source_current{false};
    std::atomic<int> width{0};
    std::atomic<int> height{0};
    std::atomic<int> magenta_pixels{0};
    std::atomic<bool> crop_valid{false};
    std::atomic<bool> bad_crop_rejected{false};
};

bool in_bounds(int x, int y, int width, int height, int frame_width, int frame_height) {
    return x >= 0 && y >= 0 && width > 0 && height > 0 &&
           x <= frame_width && y <= frame_height &&
           width <= frame_width - x && height <= frame_height - y;
}

void read_frame(Direct3D11CaptureFramePool const& sender, HWND hwnd,
                WindowIdentity const& identity, com_ptr<ID3D11Device> const& device,
                Metrics& metrics) {
    if (metrics.done.load()) return;
    try {
        auto frame = sender.TryGetNextFrame();
        if (!frame || !same_window(hwnd, identity)) {
            metrics.done = true;
            return;
        }
        metrics.source_current = true;
        auto access = frame.Surface().as<::Windows::Graphics::DirectX::Direct3D11::IDirect3DDxgiInterfaceAccess>();
        com_ptr<ID3D11Texture2D> texture;
        check_hresult(access->GetInterface(guid_of<ID3D11Texture2D>(), texture.put_void()));
        D3D11_TEXTURE2D_DESC desc{};
        texture->GetDesc(&desc);
        metrics.width = static_cast<int>(desc.Width);
        metrics.height = static_cast<int>(desc.Height);
        if (desc.Width == 0 || desc.Height == 0 ||
            desc.Width > 8192 || desc.Height > 8192 ||
            desc.Format != DXGI_FORMAT_B8G8R8A8_UNORM) {
            metrics.done = true;
            return;
        }
        metrics.crop_valid = in_bounds(0, 0, static_cast<int>(desc.Width),
                                       static_cast<int>(desc.Height),
                                       static_cast<int>(desc.Width), static_cast<int>(desc.Height));
        metrics.bad_crop_rejected = !in_bounds(static_cast<int>(desc.Width) - 4,
                                               0, 20, 20,
                                               static_cast<int>(desc.Width),
                                               static_cast<int>(desc.Height));
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
        int marker_count = 0;
        for (UINT y = 0; y < desc.Height; ++y) {
            auto row = static_cast<uint8_t const*>(mapped.pData) + y * mapped.RowPitch;
            for (UINT x = 0; x < desc.Width; ++x) {
                auto pixel = row + 4 * x; // BGRA
                if (pixel[0] > 180 && pixel[1] < 80 && pixel[2] > 180) ++marker_count;
            }
        }
        context->Unmap(staging.get(), 0);
        metrics.magenta_pixels = marker_count;
        metrics.accepted = same_window(hwnd, identity) && marker_count > 100 &&
                           metrics.crop_valid && metrics.bad_crop_rejected;
        metrics.done = true;
    } catch (...) {
        metrics.done = true;
    }
}

int main() {
    HWND hwnd = nullptr;
    char const* stage = "INIT";
    bool own_identity_verified = false;
    bool wrong_identity_rejected = false;
    bool minimized_rejected = false;
    bool destroyed_rejected = false;
    bool bad_crop_rejected = false;
    try {
        init_apartment(apartment_type::multi_threaded);
        stage = "CREATE_OWN_WINDOW";
        WNDCLASSW fixture{};
        fixture.lpfnWndProc = fixture_proc;
        fixture.hInstance = GetModuleHandleW(nullptr);
        fixture.lpszClassName = L"MithrilOwnedCaptureFixture";
        if (!RegisterClassW(&fixture)) throw hresult_error(HRESULT_FROM_WIN32(GetLastError()));
        hwnd = CreateWindowExW(0, fixture.lpszClassName, L"Mithril synthetic fixture",
                               WS_OVERLAPPEDWINDOW, 150, 150, 760, 330,
                               nullptr, nullptr, fixture.hInstance, nullptr);
        if (!hwnd) throw hresult_error(HRESULT_FROM_WIN32(GetLastError()));
        ShowWindow(hwnd, SW_SHOW);
        UpdateWindow(hwnd);
        stage = "VERIFY_OWN_WINDOW";
        WindowIdentity selected{};
        if (!inspect_window(hwnd, selected))
            throw hresult_error(E_ACCESSDENIED);
        if (selected.pid != GetCurrentProcessId()) {
            DestroyWindow(hwnd);
            hwnd = nullptr;
            std::cout << "{\"status\":\"BLOCKED\",\"scope\":\"OWN_PROCESS_SINGLE_HWND_ONLY\","
                      << "\"reason\":\"CREATED_HWND_HAS_DIFFERENT_OS_PID\","
                      << "\"capture_attempted\":false,\"raw_pixels_saved\":false,"
                      << "\"user_window_captured\":false}\n";
            return 2;
        }
        own_identity_verified = true;
        stage = "NEGATIVE_IDENTITY_CHECKS";
        HWND second = CreateWindowExW(0, fixture.lpszClassName, L"Mithril synthetic fixture",
                                      WS_OVERLAPPEDWINDOW, 220, 220, 600, 250,
                                      nullptr, nullptr, fixture.hInstance, nullptr);
        if (!second) throw hresult_error(HRESULT_FROM_WIN32(GetLastError()));
        ShowWindow(second, SW_SHOW);
        UpdateWindow(second);
        wrong_identity_rejected = !same_window(nullptr, selected) &&
            !same_window(hwnd, WindowIdentity{hwnd, selected.pid,
                         selected.started + 1, selected.path}) &&
            !same_window(second, selected);
        ShowWindow(second, SW_MINIMIZE);
        WindowIdentity ignored{};
        minimized_rejected = !inspect_window(second, ignored);
        DestroyWindow(second);
        destroyed_rejected = !inspect_window(second, ignored);
        bad_crop_rejected = !in_bounds(796, 0, 20, 20, 800, 600);
        if (!wrong_identity_rejected || !minimized_rejected || !destroyed_rejected ||
            !bad_crop_rejected) throw hresult_error(E_FAIL);
        inspection_failure = 0;
        stage = "QUERY_WGC_SUPPORT";
        bool supported = GraphicsCaptureSession::IsSupported();
        Metrics metrics;
        if (supported) {
            stage = "CREATE_D3D_DEVICE";
            com_ptr<ID3D11Device> d3d;
            check_hresult(D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr,
                                            D3D11_CREATE_DEVICE_BGRA_SUPPORT, nullptr, 0,
                                            D3D11_SDK_VERSION, d3d.put(), nullptr, nullptr));
            auto dxgi = d3d.as<IDXGIDevice>();
            com_ptr<::IInspectable> inspectable;
            check_hresult(CreateDirect3D11DeviceFromDXGIDevice(dxgi.get(), inspectable.put()));
            auto winrt_device = inspectable.as<IDirect3DDevice>();
            stage = "CREATE_CAPTURE_ITEM_FOR_OWN_HWND";
            auto activation = get_activation_factory<GraphicsCaptureItem>();
            auto interop = activation.as<IGraphicsCaptureItemInterop>();
            GraphicsCaptureItem item{nullptr};
            check_hresult(interop->CreateForWindow(
                hwnd, guid_of<ABI::Windows::Graphics::Capture::IGraphicsCaptureItem>(),
                reinterpret_cast<void**>(put_abi(item))));
            stage = "START_OWN_WINDOW_CAPTURE";
            auto pool = Direct3D11CaptureFramePool::CreateFreeThreaded(
                winrt_device, DirectXPixelFormat::B8G8R8A8UIntNormalized,
                2, item.Size());
            auto session = pool.CreateCaptureSession(item);
            auto token = pool.FrameArrived([&](auto const& sender, auto const&) {
                read_frame(sender, hwnd, selected, d3d, metrics);
            });
            session.StartCapture();
            const DWORD start = GetTickCount();
            while (!metrics.done && GetTickCount() - start < 3000) {
                MSG message{};
                while (PeekMessageW(&message, nullptr, 0, 0, PM_REMOVE)) {
                    TranslateMessage(&message);
                    DispatchMessageW(&message);
                }
                Sleep(10);
            }
            pool.FrameArrived(token);
            session.Close();
            pool.Close();
        }
        ShowWindow(hwnd, SW_MINIMIZE);
        const bool selected_minimized_rejected = !same_window(hwnd, selected);
        DestroyWindow(hwnd);
        hwnd = nullptr;
        const bool selected_destroyed_rejected = !same_window(selected.hwnd, selected);
        const bool passed = supported && metrics.accepted && wrong_identity_rejected &&
                            minimized_rejected && destroyed_rejected &&
                            selected_minimized_rejected && selected_destroyed_rejected;
        std::cout << "{\"status\":\"" << (passed ? "PASSED" : "BLOCKED")
                  << "\",\"scope\":\"OWN_PROCESS_SINGLE_HWND_ONLY\""
                  << ",\"wgc_supported\":" << (supported ? "true" : "false")
                  << ",\"frame_received\":" << (metrics.done ? "true" : "false")
                  << ",\"frame_accepted\":" << (metrics.accepted ? "true" : "false")
                  << ",\"native_identity_verified\":" << (metrics.source_current ? "true" : "false")
                  << ",\"marker_pixels\":" << metrics.magenta_pixels
                  << ",\"frame_width\":" << metrics.width
                  << ",\"frame_height\":" << metrics.height
                  << ",\"bad_crop_rejected\":" << (metrics.bad_crop_rejected ? "true" : "false")
                  << ",\"wrong_identity_rejected\":" << (wrong_identity_rejected ? "true" : "false")
                  << ",\"minimized_rejected\":" << (selected_minimized_rejected ? "true" : "false")
                  << ",\"destroyed_rejected\":" << (selected_destroyed_rejected ? "true" : "false")
                  << ",\"raw_pixels_saved\":false,\"user_window_captured\":false}\n";
        return passed ? 0 : 2;
    } catch (hresult_error const& error) {
        if (hwnd) DestroyWindow(hwnd);
        std::cout << "{\"status\":\"BLOCKED\",\"scope\":\"OWN_PROCESS_SINGLE_HWND_ONLY\","
                  << "\"stage\":\"" << stage << "\","
                  << "\"inspection_failure_code\":" << inspection_failure << ","
                  << "\"own_identity_verified\":" << (own_identity_verified ? "true" : "false") << ","
                  << "\"same_title_and_stale_creation_rejected\":" << (wrong_identity_rejected ? "true" : "false") << ","
                  << "\"minimized_rejected\":" << (minimized_rejected ? "true" : "false") << ","
                  << "\"destroyed_rejected\":" << (destroyed_rejected ? "true" : "false") << ","
                  << "\"bad_crop_rejected\":" << (bad_crop_rejected ? "true" : "false") << ","
                  << "\"hresult\":" << static_cast<uint32_t>(error.code().value)
                  << ",\"capture_attempted\":false,\"raw_pixels_saved\":false,"
                  << "\"user_window_captured\":false}\n";
        return 2;
    }
}
