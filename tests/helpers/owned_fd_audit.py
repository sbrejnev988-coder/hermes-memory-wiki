"""Single-use owned descriptor transport for offline tests, not an OS sandbox."""
from pathlib import Path
import os, sys, stat, threading
import inspect, io
RAW_OPEN = os.open
RAW_CLOSE = os.close
RAW_FDOPEN = os.fdopen
RAW_FDOPEN_SIGNATURE = inspect.signature(RAW_FDOPEN)
RAW_IO_OPEN_SIGNATURE = inspect.signature(io.open)
ACTIVE = None

class AuditFence:
    NETWORK = {'socket.connect', 'socket.connect_ex', 'socket.getaddrinfo', 'socket.bind',
               'socket.sendto', 'socket.sendmsg', 'socket.__new__', 'socket.gethostbyname',
               'socket.gethostbyaddr', 'socket.getnameinfo'}
    PROCESS = {'subprocess.Popen', '_winapi.CreateProcess', 'os.system', 'os.posix_spawn',
               'os.posix_spawnp', 'os.fork', 'os.forkpty', 'os.exec', 'os.spawn'}
    def __init__(self, owned, read_roots):
        self.owned = Path(owned).resolve()
        self.read_roots = [Path(p).resolve() for p in read_roots] + [self.owned]
        self.denials = []
        self.source_roots = []
        self.source_reads = set()
        self._pending = {}
        self._context = threading.local()
        self._lock = threading.RLock()
        self._pid = os.getpid()

    @staticmethod
    def _identity(fd):
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or os.get_inheritable(fd):
            raise PermissionError('Only non-inherited regular-file descriptors are transferable')
        handle = fd
        if os.name == 'nt':
            import msvcrt
            handle = msvcrt.get_osfhandle(fd)
        return (handle, info.st_dev, info.st_ino, info.st_mode)

    def _valid(self, fd, write, read):
        entry = self._pending.get(fd)
        if type(fd) is not int or entry is None or self._pid != os.getpid():
            return False
        pid, path, flags, identity = entry
        if pid != os.getpid() or not self.path_allowed(path, write):
            return False
        access = flags & (os.O_WRONLY | os.O_RDWR)
        if (write and access == os.O_RDONLY) or (read and access == os.O_WRONLY):
            return False
        try:
            actual = path.stat()
            return (self._identity(fd) == identity and
                    (actual.st_dev, actual.st_ino, actual.st_mode) == identity[1:])
        except (OSError, PermissionError):
            return False

    def install_tracking(self):
        def acquire(path, flags, mode=0o777, *, dir_fd=None):
            with self._lock:
                if dir_fd is not None or not isinstance(path, (str, bytes, os.PathLike)):
                    self.deny('owned-fd-acquisition')
                write = bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
                if not self.path_allowed(path, write):
                    self.deny('owned-fd-acquisition')
                self._context.acquiring = True
                try:
                    fd = RAW_OPEN(path, flags, mode)
                finally:
                    self._context.acquiring = False
                self._pending.pop(fd, None)
                try:
                    identity = self._identity(fd)
                except PermissionError:
                    return fd  # Valid directory/read operations grant no transfer authority.
                self._pending[fd] = (os.getpid(), Path(os.fsdecode(path)).resolve(), flags, identity)
                return fd

        def close(fd):
            with self._lock:
                self._pending.pop(fd, None)
                return RAW_CLOSE(fd)

        def transfer(*call_args, **call_kwargs):
            with self._lock:
                try:
                    native = RAW_FDOPEN_SIGNATURE.bind(*call_args, **call_kwargs)
                    native.apply_defaults()
                    values = native.arguments
                    effective = RAW_IO_OPEN_SIGNATURE.bind(
                        values['fd'], values['mode'], values['buffering'], values['encoding'],
                        *values['args'], **values['kwargs'])
                    effective.apply_defaults()
                except TypeError:
                    # Native grammar errors get the real API error, with no transfer token
                    # or lease consumption. The integer-open audit fence stays closed.
                    return RAW_FDOPEN(*call_args, **call_kwargs)
                values = effective.arguments
                if getattr(self._context, 'transfer', None) is not None:
                    self.deny('reentrant-owned-fd-transfer')
                fd, mode = values['file'], values['mode']
                if not isinstance(mode, str) or values['closefd'] is not True or values['opener'] is not None:
                    self.deny('owned-fd-transfer')
                write = any(ch in mode for ch in 'wax+')
                read = 'r' in mode or '+' in mode
                if not self._valid(fd, write, read):
                    self._pending.pop(fd, None)
                    self.deny('owned-fd-transfer')
                # Authority belongs to this exact native fdopen call, not a
                # same-thread callback running while its arguments are parsed.
                self._context.transfer = (fd, write, read, sys._getframe())
                try:
                    return RAW_FDOPEN(*call_args, **call_kwargs)
                finally:
                    self._context.transfer = None
                    self._pending.pop(fd, None)  # Transfer consumes authority, even on error.

        os.open, os.close, os.fdopen = acquire, close, transfer

    def path_allowed(self, value, write=False):
        if isinstance(value, int):
            return False  # Path alone never grants authority to an integer descriptor.
        path = Path(os.fsdecode(value)).resolve()
        if str(value).lower() == os.devnull.lower():
            return False
        roots = [self.owned] if write else self.read_roots
        return any(path.is_relative_to(root) for root in roots)

    def deny(self, event):
        if len(self.denials) < 100:
            self.denials.append(event)  # No payload/path/credential values retained.
        raise PermissionError('Native gate policy refused ' + event)

    def check(self, event, args):
        if event in self.NETWORK | self.PROCESS or event.startswith(('os.exec', 'os.spawn')):
            self.deny(event)
        if event == 'open':
            if isinstance(args[0], int):
                with self._lock:
                    token = getattr(self._context, 'transfer', None)
                    caller = sys._getframe(1)
                    if (token is None or type(args[0]) is not int or token[0] != args[0]
                            or caller.f_code is not RAW_FDOPEN.__code__ or caller.f_back is not token[3]
                            or not self._valid(*token[:3])):
                        self.deny('unowned-fd-open')
                    self._pending.pop(args[0], None)
                    self._context.transfer = None
                return
            if not getattr(self._context, 'acquiring', False):
                with self._lock:
                    # Untracked open can reuse a raw-closed descriptor, even at the same inode.
                    self._pending.clear()
            path = Path(os.fsdecode(args[0])).resolve()
            if path.name in {'.env', 'auth.json', 'config.yaml', 'secrets_registry.json'} and not path.is_relative_to(self.owned):
                self.deny('live-profile-read')
            mode, flags = args[1:3]
            write = ((isinstance(mode, str) and any(ch in mode for ch in 'wax+'))
                     or (isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))))
            if not self.path_allowed(args[0], write):
                self.deny(event)
            if not write and isinstance(args[0], (str, bytes, os.PathLike)):
                path = Path(os.fsdecode(args[0])).resolve()
                if path.suffix == '.py' and any(path.is_relative_to(p) for p in self.source_roots):
                    self.source_reads.add(str(path))
        if event == 'sqlite3.connect' and str(args[0]) != ':memory:':
            if not self.path_allowed(args[0], True):
                self.deny(event)
        mutations = {'os.mkdir', 'os.remove', 'os.rmdir', 'os.rename', 'os.replace',
                     'os.chmod', 'os.utime', 'os.link', 'os.symlink', 'os.truncate'}
        if event in mutations:
            fd_positions = {'os.remove': (1,), 'os.rmdir': (1,), 'os.mkdir': (2,),
                            'os.rename': (2, 3), 'os.replace': (2, 3), 'os.chmod': (2,),
                            'os.utime': (3,), 'os.link': (2, 3)}
            if any(len(args) > i and args[i] not in {None, -1} for i in fd_positions.get(event, ())):
                self.deny(event)
            count = 2 if event in {'os.rename', 'os.replace', 'os.link', 'os.symlink'} else 1
            if event == 'os.symlink':  # No fixture escape aliases, even within owned root.
                self.deny(event)
            if any(not self.path_allowed(v, True) for v in args[:count]):
                self.deny(event)
        if event in {'os.listdir', 'os.scandir'} and not self.path_allowed(args[0]):
            self.deny(event)


def install(fence):
    global ACTIVE
    ACTIVE = fence
    fence.install_tracking()
    sys.addaudithook(fence.check)
