# Copyright 2012 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contains on-disk caching functionality."""

import datetime
import errno
import hashlib
import logging
import os
import shutil
import tempfile
from typing import Optional, Tuple, Union
import urllib.parse

from chromite.lib import compression_lib
from chromite.lib import cros_build_lib
from chromite.lib import locking
from chromite.lib import osutils
from chromite.lib import retry_util
from chromite.utils import gs_urls_util


# pylint: disable=protected-access


class Error(Exception):
    """Raised on fatal errors."""


def WriteLock(f):
    """Decorator that takes a write lock."""

    def new_f(self, *args, **kwargs):
        with self._lock.write_lock():
            return f(self, *args, **kwargs)

    return new_f


class CacheReference:
    """Encapsulates operations on a cache key reference.

    CacheReferences are returned by the DiskCache.Lookup() function.  They are
    used to read from and insert into the cache.

    A typical example of using a CacheReference:

    @contextlib.contextmanager
    def FetchFromCache()
        with cache.Lookup(key) as ref:
            # If entry doesn't exist in cache already, generate it ourselves,
            # and insert it into the cache, acquiring a read lock on it in the
            # process. If the entry does exist, we grab a read lock on it.
            if not ref.Exists(lock=True):
                path = PrepareItem()
                ref.SetDefault(path, lock=True)

            # yield the path to the cached entry to consuming code.
            yield ref.path
    """

    def __init__(self, cache, key) -> None:
        self._cache = cache
        self.key = key
        self.acquired = False
        self._lock = cache._LockForKey(key)

    @property
    def path(self) -> "os.PathLike[str]":
        """Returns on-disk path to the cached item."""
        return self._cache.GetKeyPath(self.key)

    def Acquire(self) -> None:
        """Prepare the cache reference for operation.

        This must be called (either explicitly or through entering a 'with'
        context) before calling any methods that acquire locks, or mutates
        reference.
        """
        if self.acquired:
            raise AssertionError(
                "Attempting to acquire an already acquired reference."
            )

        self.acquired = True
        self._lock.__enter__()

    def Release(self) -> None:
        """Release the cache reference. Causes any held locks to be released."""
        if not self.acquired:
            raise AssertionError(
                "Attempting to release an unacquired reference."
            )

        self.acquired = False
        self._lock.__exit__(None, None, None)

    def __enter__(self):
        self.Acquire()
        return self

    def __exit__(self, *args) -> None:
        self.Release()

    def _ReadLock(self) -> None:
        self._lock.read_lock()

    @WriteLock
    def _Assign(self, path) -> None:
        self._cache._Insert(self.key, path)

    @WriteLock
    def _AssignText(self, text) -> None:
        self._cache._InsertText(self.key, text)

    @WriteLock
    def _Remove(self) -> None:
        self._cache._Remove(self.key)
        osutils.SafeUnlink(self._lock.path)

    def _Exists(self):
        return self._cache._KeyExists(self.key)

    def Assign(self, path) -> None:
        """Insert a file or a directory into the cache at the referenced key."""
        self._Assign(path)

    def AssignText(self, text) -> None:
        """Create a file containing |text| and assign it to the key.

        Args:
            text: Can be a string or an iterable.
        """
        self._AssignText(text)

    def Remove(self) -> None:
        """Removes the entry from the cache."""
        self._Remove()

    def Exists(self, lock=False):
        """Tests for existence of entry.

        Args:
            lock: If the entry exists, acquire and maintain a read lock on it.
        """
        if self._Exists():
            if lock:
                self._ReadLock()
            return True
        return False

    def SetDefault(self, default_path, lock=False) -> None:
        """Assigns default_path if the entry doesn't exist.

        Args:
            default_path: The path to assign if the entry doesn't exist.
            lock: Acquire and maintain a read lock on the entry.
        """

        if lock:
            # If a process has already taken a write lock and is in the
            # process of populating the entry, we don't want any additional
            # processes queuing up to perform the same work. By taking a read
            # lock before checking for existence we can delay the existence
            # check until the entry has been populated.
            self._ReadLock()

        if not self._Exists():
            # This will take a write lock before populating the entry and drop
            # the lock afterwards. Ideally we would just downgrade the lock to
            # a read lock.
            self._Assign(default_path)

        if lock:
            self._ReadLock()


class DiskCache:
    """Locked file system cache keyed by tuples.

    Key entries can be files or directories.  Access to the cache is provided
    through CacheReferences, which are retrieved by using the cache Lookup()
    method.
    """

    _STAGING_DIR = "staging"

    def __init__(
        self,
        cache_dir: Union[str, os.PathLike],
        cache_user: Optional[str] = None,
        lock_suffix: str = ".lock",
    ) -> None:
        # TODO(vapier): Convert this to Path.
        self._cache_dir = str(cache_dir)
        self._cache_user = cache_user
        self._lock_suffix = lock_suffix
        self.staging_dir = os.path.join(cache_dir, self._STAGING_DIR)

        osutils.SafeMakedirsNonRoot(self._cache_dir, user=self._cache_user)
        osutils.SafeMakedirsNonRoot(self.staging_dir, user=self._cache_user)

    def _KeyExists(self, key):
        return os.path.lexists(self.GetKeyPath(key))

    def GetKeyPath(self, key: Tuple[str, ...]) -> "os.PathLike[str]":
        """Get the on-disk path of a key."""
        return os.path.join(self._cache_dir, "+".join(key))

    def _LockForKey(self, key, suffix=None):
        """Returns an unacquired lock associated with a key."""
        suffix = suffix or self._lock_suffix
        key_path = self.GetKeyPath(key)
        osutils.SafeMakedirsNonRoot(
            os.path.dirname(key_path), user=self._cache_user
        )
        lock_path = os.path.join(
            self._cache_dir,
            os.path.dirname(key_path),
            os.path.basename(key_path) + suffix,
        )
        return locking.FileLock(lock_path)

    def _TempDirContext(self):
        return osutils.TempDir(base_dir=self.staging_dir)

    def _Insert(self, key, path) -> None:
        """Insert a file or a directory into the cache at a given key."""
        self._Remove(key)
        key_path = self.GetKeyPath(key)
        osutils.SafeMakedirsNonRoot(
            os.path.dirname(key_path), user=self._cache_user
        )
        shutil.move(path, key_path)

    def _InsertText(self, key, text) -> None:
        """Inserts a file containing |text| into the cache."""
        with self._TempDirContext() as tempdir:
            file_path = os.path.join(tempdir, "tempfile")
            osutils.WriteFile(file_path, text)
            self._Insert(key, file_path)

    def _Remove(self, key) -> None:
        """Remove a key from the cache."""
        if self._KeyExists(key):
            with self._TempDirContext() as tempdir:
                shutil.move(self.GetKeyPath(key), tempdir)

    def GetKey(self, path: Union[str, os.PathLike]):
        """Returns the key for an item's path in the cache."""
        path = str(path)
        if path.startswith(self._cache_dir):
            path = os.path.relpath(path, self._cache_dir)
        return tuple(path.split("+"))

    def ListKeys(self):
        """Returns a list of keys for every item present in the cache."""
        keys = []
        for root, dirs, files in os.walk(self._cache_dir):
            for f in dirs + files:
                key_path = os.path.join(root, f)
                if os.path.exists(key_path + self._lock_suffix):
                    # Test for the presence of the key's lock file to determine
                    # if this is the root key path, or some file nested within a
                    # key's dir.
                    keys.append(self.GetKey(key_path))
        return keys

    def Lookup(self, key: Tuple[str, ...]) -> CacheReference:
        """Get a reference to a given key."""
        return CacheReference(self, key)

    def DeleteStale(self, max_age):
        """Removes any item from the cache that was modified after |max_age|.

        Args:
            max_age: An instance of datetime.timedelta. Any item not modified
                within this amount of time will be removed.

        Returns:
            List of keys removed.
        """
        if not isinstance(max_age, datetime.timedelta):
            raise TypeError(
                "max_age must be an instance of datetime.timedelta."
            )
        keys_removed = []
        for key in self.ListKeys():
            path = self.GetKeyPath(key)
            mtime = max(os.path.getmtime(path), os.path.getctime(path))
            time_since_last_modify = (
                datetime.datetime.now() - datetime.datetime.fromtimestamp(mtime)
            )
            if time_since_last_modify > max_age:
                self.Lookup(key).Remove()
                keys_removed.append(key)
        return keys_removed


class RemoteCache(DiskCache):
    """Supports caching of remote objects via URI."""

    def _Fetch(
        self,
        url: str,
        local_path: str,
        *,
        hash_sha1: Optional[str] = None,
        mode: Optional[int] = None,
    ) -> None:
        """Fetch a remote file.

        Args:
            url: URL of the remote object.
            local_path: Path to store
            hash_sha1: If set, check for the SHA-1 sum.
            mode: If set, the file is chmod-ed to mode.
        """
        # We have to nest the import because gs.GSContext uses us to cache its
        # own gsutil tarball.  We know we won't get into a recursive loop though
        # as it only fetches files via non-gs URIs.
        from chromite.lib import gs

        if gs_urls_util.PathIsGs(url):
            ctx = gs.GSContext()
            ctx.Copy(url, local_path)
        else:
            # Note: unittests assume local_path is at the end.
            retry_util.RunCurl(
                ["--fail", url, "-o", local_path],
                debug_level=logging.DEBUG,
                capture_output=True,
            )

        if hash_sha1 is not None:
            actual_sha1 = Sha1File(local_path)
            if actual_sha1 != hash_sha1:
                raise Error(f"sha1({url!r}) = {actual_sha1} != {hash_sha1}")

        if mode is not None:
            osutils.Chmod(local_path, mode)

    def _Insert(self, key, url) -> None:  # pylint: disable=arguments-renamed
        """Insert a remote file into the cache."""
        o = urllib.parse.urlparse(url)
        if o.scheme in ("file", ""):
            DiskCache._Insert(self, key, o.path)
            return

        with tempfile.NamedTemporaryFile(
            dir=self.staging_dir, delete=False
        ) as local_path:
            self._Fetch(url, local_path.name)
            DiskCache._Insert(self, key, local_path.name)


def Untar(path, cwd, sudo=False) -> None:
    """Untar a tarball."""
    functor = cros_build_lib.sudo_run if sudo else cros_build_lib.run
    comp = compression_lib.CompressionType.detect_from_file(path)
    cmd = ["tar"]
    if comp != compression_lib.CompressionType.NONE:
        extra_comp_args = [compression_lib.find_compressor(comp)]
        if os.path.basename(extra_comp_args[0]) == "pbzip2":
            extra_comp_args.append("--ignore-trailing-garbage=1")
        elif os.path.basename(extra_comp_args[0]).startswith("zstd"):
            extra_comp_args.append("-f")
        cmd += ["-I", " ".join(extra_comp_args)]
    functor(
        cmd + ["-xpf", path],
        cwd=cwd,
        debug_level=logging.DEBUG,
        capture_output=True,
    )


class TarballCache(RemoteCache):
    """Supports caching of extracted tarball contents."""

    # pylint: disable-next=arguments-renamed
    def _Insert(self, key, tarball_path) -> None:
        """Insert a tarball and its extracted contents into the cache.

        Download the tarball first if a URL is provided as tarball_path.
        """
        with osutils.TempDir(
            prefix="tarball-cache", base_dir=self.staging_dir
        ) as tempdir:
            o = urllib.parse.urlsplit(tarball_path)
            if o.scheme == "file":
                tarball_path = o.path
            elif o.scheme:
                url = tarball_path
                tarball_path = os.path.join(tempdir, os.path.basename(o.path))
                self._Fetch(url, tarball_path)

            extract_path = os.path.join(tempdir, "extract")
            os.mkdir(extract_path)
            Untar(tarball_path, extract_path)
            DiskCache._Insert(self, key, extract_path)

    def _KeyExists(self, key):
        """Specialized DiskCache._KeyExits that ignores empty directories.

        The normal _KeyExists just checks to see if the key path exists in the
        cache directory. Many tests mock out run then fetch a tarball. The mock
        blocks untarring into it. This leaves behind an empty dir which blocks
        future untarring in non-test scripts.

        See crbug.com/468838
        """
        # Wipe out empty directories before testing for existence.
        key_path = self.GetKeyPath(key)

        try:
            os.rmdir(key_path)
        except OSError as ex:
            if ex.errno not in (errno.ENOTEMPTY, errno.ENOENT):
                raise

        return os.path.exists(key_path)


def Sha1File(path: Union[str, os.PathLike]) -> str:
    """Computes the SHA-1 checksum of path as a hex string."""
    # Reusable buffer to reduce allocations.
    buf = bytearray(4096)
    view = memoryview(buf)
    sha1 = hashlib.sha1()

    with open(path, "rb") as fileobj:
        while True:
            size = fileobj.readinto(buf)
            if size == 0:
                # EOF
                break
            sha1.update(view[:size])

    return sha1.hexdigest()
