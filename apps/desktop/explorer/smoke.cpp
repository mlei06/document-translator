#include <windows.h>
#include <shobjidl.h>
#include <iostream>
#pragma comment(lib,"ole32.lib")
#pragma comment(lib,"uuid.lib")
#pragma comment(lib,"shell32.lib")
int wmain(int argc,wchar_t**argv) {
 if(argc!=2 && argc!=3)return 2;
 HRESULT initialized=CoInitializeEx(nullptr,COINIT_APARTMENTTHREADED);
 if(FAILED(initialized))return 3;
 auto module=LoadLibraryW(argv[1]);if(!module)return 4;
 using FactoryFn=HRESULT(WINAPI*)(REFCLSID,REFIID,void**);
 auto factoryFn=reinterpret_cast<FactoryFn>(GetProcAddress(module,"DllGetClassObject"));
 CLSID id;CLSIDFromString(L"{415E3ACA-094E-4A40-A6B7-58A6DA8D39A8}",&id);
 IClassFactory*factory=nullptr;
 if(!factoryFn||FAILED(factoryFn(id,IID_PPV_ARGS(&factory))))return 5;
 IExplorerCommand*command=nullptr;
 if(FAILED(factory->CreateInstance(nullptr,IID_PPV_ARGS(&command))))return 6;
 PWSTR title=nullptr;if(FAILED(command->GetTitle(nullptr,&title)))return 7;
 std::wcout<<L"Root: "<<title<<L"\n";CoTaskMemFree(title);
 IEnumExplorerCommand*enumerator=nullptr;if(FAILED(command->EnumSubCommands(&enumerator)))return 8;
 IExplorerCommand*child=nullptr;ULONG count=0;int total=0;
 while(enumerator->Next(1,&child,&count)==S_OK) {
  title=nullptr;if(FAILED(child->GetTitle(nullptr,&title)))return 9;
  std::wcout<<L"Shortcut: "<<title<<L"\n";CoTaskMemFree(title);
  if(argc==3 && total==0) {
   IShellItem*item=nullptr;IShellItemArray*selection=nullptr;
   if(FAILED(SHCreateItemFromParsingName(argv[2],nullptr,IID_PPV_ARGS(&item))))return 11;
   auto result=SHCreateShellItemArrayFromShellItem(item,IID_PPV_ARGS(&selection));item->Release();
   if(FAILED(result))return 12;
   result=child->Invoke(selection,nullptr);selection->Release();if(FAILED(result))return 13;
   std::cout<<"Structured Explorer invocation passed\n";
  }
  child->Release();++total;
 }
 enumerator->Release();command->Release();factory->Release();
 auto unload=reinterpret_cast<HRESULT(WINAPI*)()>(GetProcAddress(module,"DllCanUnloadNow"));
 if(!unload||unload()!=S_OK)return 10;
 FreeLibrary(module);CoUninitialize();std::cout<<"COM ownership and enumeration passed: "<<total<<"\n";return 0;
}
