"""Read and save Shell Links with the Windows SDK's Unicode interfaces."""
import ctypes
import os
from uuid import UUID


class ShellLinkError(OSError):
    def __init__(self, operation, hresult):
        super().__init__(operation)
        self.operation = operation
        self.hresult = f'0x{hresult & 0xffffffff:08X}'


def _guid(value):
    return (ctypes.c_ubyte * 16).from_buffer_copy(UUID(value).bytes_le)


def _check(operation, result):
    if result < 0:
        raise ShellLinkError(operation, result)


def _method(instance, slot, *argtypes):
    # Each COM interface begins with its method table; its pointer is the first argument.
    table = ctypes.cast(instance, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)(table[slot])


def prepare_link(existing, stage, executable, arguments, owner):
    """Return False for an identical owned link, or save a fresh link to stage."""
    ole = ctypes.WinDLL('ole32')
    ptr = ctypes.c_void_p
    out_ptr = ctypes.POINTER(ptr)
    text = ctypes.c_wchar_p
    ole.CoInitializeEx.argtypes = [ptr, ctypes.c_ulong]
    ole.CoCreateInstance.argtypes = [ptr, ptr, ctypes.c_ulong, ptr, out_ptr]
    ole.CoUninitialize.argtypes = []
    ole.CoUninitialize.restype = None
    init = ole.CoInitializeEx(None, 2)  # COINIT_APARTMENTTHREADED
    if init & 0xffffffff != 0x80010106:  # RPC_E_CHANGED_MODE: use the thread's existing apartment.
        _check('initialize', init)
    shell_link, persist_file = ptr(), ptr()
    try:
        clsid = _guid('00021401-0000-0000-c000-000000000046')
        iid_link_w = _guid('000214f9-0000-0000-c000-000000000046')
        iid_persist = _guid('0000010b-0000-0000-c000-000000000046')
        _check('create-link', ole.CoCreateInstance(clsid, None, 1, iid_link_w, ctypes.byref(shell_link)))
        query_interface = _method(shell_link, 0, ptr, out_ptr)
        _check('query-persistence', query_interface(shell_link, iid_persist, ctypes.byref(persist_file)))
        if existing is not None:
            # Unknown formats and unmanaged descriptions are never replaced.
            load = _method(persist_file, 5, text, ctypes.c_ulong)
            if load(persist_file, str(existing), 0) < 0:
                raise FileExistsError(existing)
            buffer = ctypes.create_unicode_buffer(32768)
            get_description = _method(shell_link, 6, text, ctypes.c_int)
            if get_description(shell_link, buffer, len(buffer)) < 0 or buffer.value != owner:
                raise FileExistsError(existing)
            get_path = _method(shell_link, 3, text, ctypes.c_int, ptr, ctypes.c_ulong)
            _check('read-target', get_path(shell_link, buffer, len(buffer), None, 4))  # SLGP_RAWPATH
            same_target = os.path.normcase(buffer.value) == os.path.normcase(executable)
            get_arguments = _method(shell_link, 10, text, ctypes.c_int)
            _check('read-arguments', get_arguments(shell_link, buffer, len(buffer)))
            if same_target and buffer.value == arguments:
                return False

        set_path = _method(shell_link, 20, text)
        set_arguments = _method(shell_link, 11, text)
        set_description = _method(shell_link, 7, text)
        _check('set-target', set_path(shell_link, executable))
        _check('set-arguments', set_arguments(shell_link, arguments))
        _check('set-owner', set_description(shell_link, owner))
        save = _method(persist_file, 6, text, ctypes.c_int)
        _check('save-link', save(persist_file, str(stage), 1))
        return True
    finally:
        for interface in (persist_file, shell_link):
            if interface:
                _method(interface, 2)(interface)  # IUnknown::Release
        if init >= 0:
            ole.CoUninitialize()
