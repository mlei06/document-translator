// Thin Windows 11 Explorer activation. No inference, parsing, or HTTP in
// Explorer.
#define WIN32_LEAN_AND_MEAN
#include <atomic>
#include <filesystem>
#include <new>
#include <shlobj.h>
#include <shlwapi.h>
#include <shobjidl.h>
#include <string>
#include <vector>
#include <windows.h>

#pragma comment(lib, "ole32.lib")
#pragma comment(lib, "shell32.lib")
#pragma comment(lib, "shlwapi.lib")
#pragma comment(lib, "advapi32.lib")

static const CLSID CommandId = {
    0x415e3aca,
    0x094e,
    0x4a40,
    {0xa6, 0xb7, 0x58, 0xa6, 0xda, 0x8d, 0x39, 0xa8}};
static std::atomic_long objects{0};
static HMODULE moduleHandle;

static std::vector<std::wstring> shortcuts() {
  DWORD bytes = 0;
  auto status =
      RegGetValueW(HKEY_CURRENT_USER, L"Software\\Lenny\\Translator",
                   L"Shortcuts", RRF_RT_REG_MULTI_SZ, nullptr, nullptr, &bytes);
  if (status == ERROR_FILE_NOT_FOUND)
    return {L"en"};
  if (status != ERROR_SUCCESS || bytes > 1024)
    return {};
  std::vector<wchar_t> data(bytes / sizeof(wchar_t) + 2, 0);
  if (RegGetValueW(HKEY_CURRENT_USER, L"Software\\Lenny\\Translator",
                   L"Shortcuts", RRF_RT_REG_MULTI_SZ, nullptr, data.data(),
                   &bytes) != ERROR_SUCCESS)
    return {};
  std::vector<std::wstring> result;
  for (const wchar_t *p = data.data(); *p; p += wcslen(p) + 1) {
    std::wstring code(p);
    if (code == L"en" || code == L"zh" || code == L"ja" || code == L"es")
      result.push_back(code);
  }
  return result;
}

static std::wstring quote(const std::wstring &value) {
  std::wstring result = L"\"";
  size_t slashes = 0;
  for (auto c : value) {
    if (c == L'\\') {
      ++slashes;
      continue;
    }
    if (c == L'\"') {
      result.append(slashes * 2 + 1, L'\\');
      result += c;
    } else {
      result.append(slashes, L'\\');
      result += c;
    }
    slashes = 0;
  }
  result.append(slashes * 2, L'\\');
  return result + L"\"";
}

static std::string jsonString(const std::wstring &value) {
  int length = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, value.data(),
                                   static_cast<int>(value.size()), nullptr, 0,
                                   nullptr, nullptr);
  std::string utf8(length, '\0');
  WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, value.data(),
                      static_cast<int>(value.size()), utf8.data(), length,
                      nullptr, nullptr);
  std::string result = "\"";
  for (unsigned char c : utf8) {
    if (c == '"' || c == '\\') {
      result += '\\';
      result += static_cast<char>(c);
    } else if (c < 32) {
      char escaped[7];
      sprintf_s(escaped, "\\u%04x", c);
      result += escaped;
    } else
      result += static_cast<char>(c);
  }
  return result + '"';
}

static HRESULT activate(IShellItemArray *items, const std::wstring &target) {
  if (!items)
    return E_INVALIDARG;
  DWORD count = 0;
  HRESULT hr = items->GetCount(&count);
  if (FAILED(hr) || !count)
    return E_INVALIDARG;
  std::string payload =
      "{\"version\":1,\"target\":" + jsonString(target) + ",\"paths\":[";
  for (DWORD i = 0; i < count; ++i) {
    IShellItem *item = nullptr;
    PWSTR path = nullptr;
    hr = items->GetItemAt(i, &item);
    if (FAILED(hr))
      return hr;
    hr = item->GetDisplayName(SIGDN_FILESYSPATH, &path);
    item->Release();
    if (FAILED(hr))
      return hr;
    if (i)
      payload += ',';
    payload += jsonString(path);
    CoTaskMemFree(path);
  }
  payload += "]}";
  PWSTR local = nullptr;
  hr = SHGetKnownFolderPath(FOLDERID_LocalAppData, 0, nullptr, &local);
  if (FAILED(hr))
    return hr;
  std::filesystem::path directory =
      std::filesystem::path(local) / L"Lenny" / L"Translator" / L"activations";
  CoTaskMemFree(local);
  std::error_code error;
  std::filesystem::create_directories(directory, error);
  if (error)
    return HRESULT_FROM_WIN32(error.value());
  GUID guid;
  CoCreateGuid(&guid);
  wchar_t id[40];
  StringFromGUID2(guid, id, 40);
  auto activation = directory / (std::wstring(id) + L".json");
  HANDLE file = CreateFileW(activation.c_str(), GENERIC_WRITE, 0, nullptr,
                            CREATE_NEW, FILE_ATTRIBUTE_NORMAL, nullptr);
  if (file == INVALID_HANDLE_VALUE)
    return HRESULT_FROM_WIN32(GetLastError());
  DWORD written = 0;
  BOOL wrote = WriteFile(file, payload.data(),
                         static_cast<DWORD>(payload.size()), &written, nullptr);
  FlushFileBuffers(file);
  CloseHandle(file);
  if (!wrote || written != payload.size()) {
    DeleteFileW(activation.c_str());
    return E_FAIL;
  }
  wchar_t module[32768];
  if (!GetModuleFileNameW(moduleHandle, module, 32768))
    return HRESULT_FROM_WIN32(GetLastError());
  auto executable =
      std::filesystem::path(module).parent_path() / L"lenny-desktop.exe";
  auto command = quote(executable.wstring()) + L" --activation " +
                 quote(activation.wstring());
  STARTUPINFOW startup = {sizeof(startup)};
  PROCESS_INFORMATION process = {};
  if (!CreateProcessW(executable.c_str(), command.data(), nullptr, nullptr,
                      FALSE, 0, nullptr, executable.parent_path().c_str(),
                      &startup, &process)) {
    hr = HRESULT_FROM_WIN32(GetLastError());
    DeleteFileW(activation.c_str());
    return hr;
  }
  CloseHandle(process.hThread);
  CloseHandle(process.hProcess);
  return S_OK;
}

class Command;
class Enumeration final : public IEnumExplorerCommand {
  std::atomic_ulong refs{1};
  std::vector<std::wstring> codes;
  size_t index = 0;

public:
  explicit Enumeration(std::vector<std::wstring> value)
      : codes(std::move(value)) {
    ++objects;
  }
  ~Enumeration() { --objects; }
  HRESULT STDMETHODCALLTYPE QueryInterface(REFIID riid, void **out) override {
    if (!out)
      return E_POINTER;
    *out = nullptr;
    if (riid == IID_IUnknown || riid == IID_IEnumExplorerCommand) {
      *out = this;
      AddRef();
      return S_OK;
    }
    return E_NOINTERFACE;
  }
  ULONG STDMETHODCALLTYPE AddRef() override { return ++refs; }
  ULONG STDMETHODCALLTYPE Release() override {
    auto value = --refs;
    if (!value)
      delete this;
    return value;
  }
  HRESULT STDMETHODCALLTYPE Next(ULONG count, IExplorerCommand **out,
                                 ULONG *fetched) override;
  HRESULT STDMETHODCALLTYPE Skip(ULONG count) override {
    size_t available = codes.size() - index;
    index += min(static_cast<size_t>(count), available);
    return available >= count ? S_OK : S_FALSE;
  }
  HRESULT STDMETHODCALLTYPE Reset() override {
    index = 0;
    return S_OK;
  }
  HRESULT STDMETHODCALLTYPE Clone(IEnumExplorerCommand **out) override {
    if (!out)
      return E_POINTER;
    auto copy = new (std::nothrow) Enumeration(codes);
    if (!copy)
      return E_OUTOFMEMORY;
    copy->index = index;
    *out = copy;
    return S_OK;
  }
};

class Command final : public IExplorerCommand {
  std::atomic_ulong refs{1};
  std::wstring target;

public:
  explicit Command(std::wstring value = L"") : target(std::move(value)) {
    ++objects;
  }
  ~Command() { --objects; }
  HRESULT STDMETHODCALLTYPE QueryInterface(REFIID riid, void **out) override {
    if (!out)
      return E_POINTER;
    *out = nullptr;
    if (riid == IID_IUnknown || riid == IID_IExplorerCommand) {
      *out = this;
      AddRef();
      return S_OK;
    }
    return E_NOINTERFACE;
  }
  ULONG STDMETHODCALLTYPE AddRef() override { return ++refs; }
  ULONG STDMETHODCALLTYPE Release() override {
    auto value = --refs;
    if (!value)
      delete this;
    return value;
  }
  HRESULT STDMETHODCALLTYPE GetTitle(IShellItemArray *, PWSTR *title) override {
    const wchar_t *text = target.empty()    ? L"Translate"
                          : target == L"en" ? L"English"
                          : target == L"zh" ? L"Chinese"
                          : target == L"ja" ? L"Japanese"
                                            : L"Spanish";
    return SHStrDupW(text, title);
  }
  HRESULT STDMETHODCALLTYPE GetIcon(IShellItemArray *, PWSTR *icon) override {
    *icon = nullptr;
    return E_NOTIMPL;
  }
  HRESULT STDMETHODCALLTYPE GetToolTip(IShellItemArray *, PWSTR *tip) override {
    *tip = nullptr;
    return E_NOTIMPL;
  }
  HRESULT STDMETHODCALLTYPE GetCanonicalName(GUID *guid) override {
    *guid = CommandId;
    if (!target.empty())
      guid->Data1 ^= static_cast<ULONG>(target[0]) * 256 + target[1];
    return S_OK;
  }
  HRESULT STDMETHODCALLTYPE GetState(IShellItemArray *, BOOL,
                                     EXPCMDSTATE *state) override {
    *state = target.empty() && shortcuts().empty() ? ECS_HIDDEN : ECS_ENABLED;
    return S_OK;
  }
  HRESULT STDMETHODCALLTYPE Invoke(IShellItemArray *items,
                                   IBindCtx *) override {
    if (target.empty())
      return E_NOTIMPL;
    return activate(items, target);
  }
  HRESULT STDMETHODCALLTYPE GetFlags(EXPCMDFLAGS *flags) override {
    *flags = target.empty() ? ECF_HASSUBCOMMANDS : ECF_DEFAULT;
    return S_OK;
  }
  HRESULT STDMETHODCALLTYPE
  EnumSubCommands(IEnumExplorerCommand **out) override {
    if (!out)
      return E_POINTER;
    *out = nullptr;
    if (!target.empty())
      return E_NOTIMPL;
    *out = new (std::nothrow) Enumeration(shortcuts());
    return *out ? S_OK : E_OUTOFMEMORY;
  }
};

HRESULT Enumeration::Next(ULONG count, IExplorerCommand **out, ULONG *fetched) {
  if (!out || (!fetched && count != 1))
    return E_POINTER;
  ULONG total = 0;
  while (total < count && index < codes.size()) {
    out[total] = new (std::nothrow) Command(codes[index]);
    if (!out[total])
      return E_OUTOFMEMORY;
    ++total;
    ++index;
  }
  if (fetched)
    *fetched = total;
  return total == count ? S_OK : S_FALSE;
}

class Factory final : public IClassFactory {
  std::atomic_ulong refs{1};

public:
  Factory() { ++objects; }
  ~Factory() { --objects; }
  HRESULT STDMETHODCALLTYPE QueryInterface(REFIID riid, void **out) override {
    if (!out)
      return E_POINTER;
    *out = nullptr;
    if (riid == IID_IUnknown || riid == IID_IClassFactory) {
      *out = this;
      AddRef();
      return S_OK;
    }
    return E_NOINTERFACE;
  }
  ULONG STDMETHODCALLTYPE AddRef() override { return ++refs; }
  ULONG STDMETHODCALLTYPE Release() override {
    auto value = --refs;
    if (!value)
      delete this;
    return value;
  }
  HRESULT STDMETHODCALLTYPE CreateInstance(IUnknown *outer, REFIID riid,
                                           void **out) override {
    if (outer)
      return CLASS_E_NOAGGREGATION;
    auto value = new (std::nothrow) Command();
    if (!value)
      return E_OUTOFMEMORY;
    auto hr = value->QueryInterface(riid, out);
    value->Release();
    return hr;
  }
  HRESULT STDMETHODCALLTYPE LockServer(BOOL lock) override {
    if (lock)
      ++objects;
    else
      --objects;
    return S_OK;
  }
};
STDAPI DllGetClassObject(REFCLSID clsid, REFIID riid, void **out) {
  if (clsid != CommandId)
    return CLASS_E_CLASSNOTAVAILABLE;
  auto factory = new (std::nothrow) Factory();
  if (!factory)
    return E_OUTOFMEMORY;
  auto hr = factory->QueryInterface(riid, out);
  factory->Release();
  return hr;
}
STDAPI DllCanUnloadNow() { return objects == 0 ? S_OK : S_FALSE; }
BOOL WINAPI DllMain(HINSTANCE module, DWORD reason, LPVOID) {
  if (reason == DLL_PROCESS_ATTACH) {
    moduleHandle = module;
    DisableThreadLibraryCalls(module);
  }
  return TRUE;
}
