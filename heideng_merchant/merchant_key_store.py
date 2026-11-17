"""Merchant-only opt-in OS-protected secret storage. Never a plaintext fallback."""
from __future__ import annotations
import hashlib, os, sys
from pathlib import Path
from .safety import SafetyError, safe_join


def _path(state):return safe_join(Path(state).resolve(), 'secrets/lts4ai.dpapi')


def _dpapi(data, *, decrypt=False):
    import ctypes
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]
    buffer=ctypes.create_string_buffer(data)
    source=Blob(len(data),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_ubyte)));output=Blob()
    crypt=ctypes.WinDLL('crypt32',use_last_error=True)
    function=crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
    function.restype=wintypes.BOOL
    if not function(ctypes.byref(source),None,None,None,None,1,ctypes.byref(output)):
        raise SafetyError('merchant-os-secret-storage-unavailable')
    try:return ctypes.string_at(output.data,output.size)
    finally:
        kernel=ctypes.WinDLL('kernel32',use_last_error=True);kernel.LocalFree.argtypes=[ctypes.c_void_p];kernel.LocalFree.restype=ctypes.c_void_p
        kernel.LocalFree(output.data)


def _mac_keychain(state,operation,value=None):
    """Native Security.framework; no key in CLI args, logs, or plaintext files."""
    import ctypes
    cf=ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
    sec=ctypes.CDLL('/System/Library/Frameworks/Security.framework/Security')
    pointer=ctypes.c_void_p;owned=[]
    cf.CFStringCreateWithCString.argtypes=[pointer,ctypes.c_char_p,ctypes.c_uint32];cf.CFStringCreateWithCString.restype=pointer
    cf.CFDataCreate.argtypes=[pointer,pointer,ctypes.c_long];cf.CFDataCreate.restype=pointer
    cf.CFDictionaryCreateMutable.argtypes=[pointer,ctypes.c_long,pointer,pointer];cf.CFDictionaryCreateMutable.restype=pointer
    cf.CFDictionarySetValue.argtypes=[pointer,pointer,pointer];cf.CFRelease.argtypes=[pointer]
    cf.CFDataGetLength.argtypes=[pointer];cf.CFDataGetLength.restype=ctypes.c_long
    cf.CFDataGetBytePtr.argtypes=[pointer];cf.CFDataGetBytePtr.restype=pointer
    sec.SecItemCopyMatching.argtypes=[pointer,ctypes.POINTER(pointer)];sec.SecItemCopyMatching.restype=ctypes.c_int32
    sec.SecItemUpdate.argtypes=[pointer,pointer];sec.SecItemUpdate.restype=ctypes.c_int32
    sec.SecItemAdd.argtypes=[pointer,pointer];sec.SecItemAdd.restype=ctypes.c_int32
    sec.SecItemDelete.argtypes=[pointer];sec.SecItemDelete.restype=ctypes.c_int32
    def constant(lib,name):return pointer.in_dll(lib,name).value
    def text(v):
        result=cf.CFStringCreateWithCString(None,v.encode('utf-8'),0x08000100);owned.append(result);return result
    def dictionary():
        result=cf.CFDictionaryCreateMutable(None,0,None,None);owned.append(result);return result
    def put(d,key,v):cf.CFDictionarySetValue(d,constant(sec,key),v)
    try:
        query=dictionary();put(query,'kSecClass',constant(sec,'kSecClassGenericPassword'))
        service='heideng-merchant-lts4ai-'+hashlib.sha256(str(Path(state).resolve()).encode()).hexdigest()[:24]
        put(query,'kSecAttrService',text(service));put(query,'kSecAttrAccount',text('merchant'))
        if operation=='read':
            put(query,'kSecReturnData',constant(cf,'kCFBooleanTrue'));output=pointer()
            status=sec.SecItemCopyMatching(query,ctypes.byref(output))
            if status==-25300:return None
            if status!=0:raise SafetyError('merchant-macos-keychain-unavailable')
            try:
                size=cf.CFDataGetLength(output)
                if not 0<size<=8192:raise SafetyError('merchant-os-secret-storage-invalid')
                return ctypes.string_at(cf.CFDataGetBytePtr(output),size).decode('utf-8')
            finally:cf.CFRelease(output)
        if operation=='forget':status=sec.SecItemDelete(query)
        else:
            encoded=value.encode('utf-8');buffer=ctypes.create_string_buffer(encoded)
            data=cf.CFDataCreate(None,buffer,len(encoded));owned.append(data)
            attrs=dictionary();put(attrs,'kSecValueData',data)
            status=sec.SecItemUpdate(query,attrs)
            if status==-25300:
                put(query,'kSecValueData',data);status=sec.SecItemAdd(query,None)
        if status not in (0,-25300 if operation=='forget' else 0):raise SafetyError('merchant-macos-keychain-unavailable')
    finally:
        for item in reversed(owned):
            if item:cf.CFRelease(item)


def _legacy_path(state):return safe_join(Path(state).resolve(), 'lts4ai.key.dpapi')


def read_key(state):
    try:
        if os.name=='nt':
            path=_path(state)
            if not path.is_file():
                # Only the merchant product's own previous file, never personal Skill/company credential paths.
                legacy=_legacy_path(state)
                if not legacy.is_file():return None
                value=_dpapi(legacy.read_bytes(),decrypt=True).decode('utf-8')
                store_key(state,value)
                return value  # Preserve the old encrypted blob as recovery evidence.
            if path.stat().st_size>32768:raise SafetyError('merchant-os-secret-storage-invalid')
            return _dpapi(path.read_bytes(),decrypt=True).decode('utf-8')
        if sys.platform=='darwin':
            return _mac_keychain(state,'read')
        return None
    except SafetyError:raise
    except Exception:raise SafetyError('merchant-os-secret-storage-unavailable') from None


def store_key(state,value):
    if not isinstance(value,str) or not value.strip() or len(value.encode())>8192:raise SafetyError('merchant-key-input-invalid')
    try:
        if os.name=='nt':
            encrypted=_dpapi(value.strip().encode('utf-8'));path=_path(state);path.parent.mkdir(parents=True,exist_ok=True)
            import uuid
            temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
            temporary.write_bytes(encrypted);temporary.replace(path);return
        if sys.platform=='darwin':
            _mac_keychain(state,'store',value.strip());return
        raise SafetyError('merchant-os-secret-storage-unsupported')
    except SafetyError:raise
    except Exception:raise SafetyError('merchant-os-secret-storage-unavailable') from None


def forget_key(state):
    if os.name=='nt':_path(state).unlink(missing_ok=True)
    elif sys.platform=='darwin':
        _mac_keychain(state,'forget')
