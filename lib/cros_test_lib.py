# Copyright 2011 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Cros unit test library, with utility functions."""

from __future__ import annotations

import contextlib
import io
import logging
import os
from pathlib import Path
import re
import sys
import time
import types
from typing import (
    Any,
    Callable,
    Dict,
    Generator,
    Iterable,
    Iterator,
    List,
    NamedTuple,
    Optional,
    Sequence,
    Type,
    Union,
)
import unittest
from unittest import mock

from chromite.cli import command
from chromite.lib import cache
from chromite.lib import compression_lib
from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import operation
from chromite.lib import osutils
from chromite.lib import partial_mock
from chromite.lib import portage_util
from chromite.lib import timeout_util
from chromite.utils import memoize
from chromite.utils import shell_util


# Whether the current test session has --network tests enabled.  Since pytest
# doesn't have a way of detecting markers dynamically, we set this with a global
# fixture for other places to read.  This does not indicate whether the current
# test itself has pytest.mark.network_test enabled, only the overall session.
NETWORK_TESTS_ENABLED = False


class File(NamedTuple):
    """A single file with contents.

    For use with CreateOnDiskHierarchy.
    """

    name: str
    contents: str = ""


class Directory(NamedTuple):
    """A single directory with entries.

    For use with CreateOnDiskHierarchy.
    """

    name: str
    contents: Iterable[Directory | File | str] = ()


def _FlattenStructure(
    base_path: Union[str, Path], dir_struct: Sequence[Union[Directory, str]]
) -> List[str]:
    """Converts a directory structure to a list of paths."""
    flattened = []
    for obj in dir_struct:
        if isinstance(obj, Directory):
            new_base = os.path.join(base_path, obj.name).rstrip(os.sep)
            flattened.append(new_base + os.sep)
            flattened.extend(_FlattenStructure(new_base, obj.contents))
        else:
            assert isinstance(obj, str)
            flattened.append(os.path.join(base_path, obj))
    return flattened


def _walk_structure(
    base: Path, struct: Iterable[Directory | str]
) -> Iterator[tuple[Path, Directory | File]]:
    """Walk the directory structure and yield each path one at a time.

    A Directory will be yielded once for itself, and then each subpath it
    contains.
    """
    for obj in struct:
        if isinstance(obj, Directory):
            yield (base, obj)
            yield from _walk_structure(base / obj.name, obj.contents)
        elif isinstance(obj, File):
            yield (base, obj)
        else:
            assert isinstance(obj, str)
            if obj.endswith(os.sep) or not obj:
                yield (base, Directory(obj))
            else:
                yield (base, File(obj))


def CreateOnDiskHierarchy(
    base_path: Union[str, Path], dir_struct: Sequence[Union[Directory, str]]
) -> None:
    """Creates on-disk representation of an in-memory directory structure.

    Args:
        base_path: The absolute root of the directory structure.
        dir_struct: A recursively defined data structure that represents a
            directory tree.  The basic form is a list.  Elements can be file
            names or cros_test_lib.Directory objects.  The 'contents' attribute
            of Directory types is a directory structure representing the
            contents of the directory.
            Examples:
                - ['file1', 'file2']
                - ['file1', Directory('directory', ['deepfile1', 'deepfile2']),
                    'file2']
    """
    if isinstance(base_path, str):
        base_path = Path(base_path)

    for dirpath, obj in _walk_structure(base_path, dir_struct):
        if isinstance(obj, Directory):
            osutils.SafeMakedirs(dirpath / obj.name)
        elif obj.contents:
            osutils.WriteFile(dirpath / obj.name, obj.contents, makedirs=True)
        else:
            osutils.Touch(dirpath / obj.name, makedirs=True)


def _VerifyDirectoryIterables(
    existing: Iterable[Union[str, "os.PathLike[str]"]],
    expected: Iterable[Union[str, "os.PathLike[str]"]],
) -> None:
    """Compare two iterables representing contents of a directory.

    Paths in |existing| and |expected| will be compared for exact match.

    Args:
        existing: An iterable containing paths that exist.
        expected: An iterable of paths that are expected.

    Raises:
        AssertionError when there is any divergence between |existing| and
        |expected|.
    """

    def FormatPaths(paths: Iterable[str]) -> str:
        return "\n".join(sorted(paths))

    existing = set(str(x) for x in existing)
    expected = set(str(x) for x in expected)

    unexpected = existing - expected
    if unexpected:
        raise AssertionError(
            "Found unexpected paths:\n%s"
            % FormatPaths(unexpected)  # type: ignore[arg-type]
        )
    missing = expected - existing
    if missing:
        raise AssertionError(
            "These files were expected but not found:\n%s"
            % FormatPaths(missing)  # type: ignore[arg-type]
        )


def VerifyOnDiskHierarchy(
    base_path: Union[str, Path], dir_struct: Sequence[Union[Directory, str]]
) -> None:
    """Verify that an on-disk directory tree exactly matches a given structure.

    Args:
        base_path: See CreateOnDiskHierarchy()
        dir_struct: See CreateOnDiskHierarchy()

    Raises:
        AssertionError when there is any divergence between the on-disk
        structure and the structure specified by 'dir_struct'.
    """
    # Make sure the arg ends with a / if it's a dir to more reliably assert.
    existing = [
        str(x) + "/" if x.is_dir() else str(x)
        for x in osutils.DirectoryIterator(Path(base_path))
    ]
    expected = _FlattenStructure(base_path, dir_struct)
    _VerifyDirectoryIterables(existing, expected)


def VerifyTarball(
    tarball: Union[str, Path], dir_struct: Sequence[Union[Directory, str]]
) -> None:
    """Compare the contents of a tarball against a directory structure.

    Args:
        tarball: Path to the tarball.
        dir_struct: See CreateOnDiskHierarchy()

    Raises:
        AssertionError when there is any divergence between the tarball and the
        structure specified by 'dir_struct'.
    """
    compression_type = compression_lib.CompressionType.detect_from_file(tarball)
    compressor = compression_lib.find_compressor(compression_type)
    result = cros_build_lib.run(
        [
            "tar",
            "--use-compress-program",
            shell_util.quote(compressor),
            "-tf",
            tarball,
        ],
        capture_output=True,
        encoding="utf-8",
    )
    contents = result.stdout.splitlines()
    normalized = set()
    for p in contents:
        norm = os.path.normpath(p)
        if p.endswith("/"):
            norm += "/"
        if norm in normalized:
            raise AssertionError(
                "Duplicate entry %r found in %r!" % (norm, tarball)
            )
        normalized.add(norm)

    expected = _FlattenStructure("", dir_struct)
    _VerifyDirectoryIterables(normalized, expected)


class StackedSetup(type):
    """Metaclass to simplify unit testing and make it more robust.

    A metaclass alters the way that classes are initialized, enabling us to
    modify the class dictionary prior to the class being created. We use this
    feature here to modify the way that unit tests work a bit.

    This class does three things:
      1) When a test case is set up or torn down, we now run all setUp and
         tearDown methods in the inheritance tree.
      2) If a setUp or tearDown method fails, we still run tearDown methods
         for any test classes that were partially or completely set up.
      3) All test cases time out after TEST_CASE_TIMEOUT seconds.

    Use by including this line in the class signature:
      class ...(..., metaclass=StackedSetup)

    Since cros_test_lib.TestCase uses this metaclass, all derivatives of
    TestCase also inherit the above behavior (unless they override the metaclass
    attribute manually).
    """

    TEST_CASE_TIMEOUT = 10 * 60

    def __new__(cls, clsname, bases, scope):  # type: ignore
        """Generate new class with pointers to original funcs & our helpers."""
        if "setUp" in scope:
            scope["__raw_setUp__"] = scope.pop("setUp")
        scope["setUp"] = cls._stacked_setUp

        if "tearDown" in scope:
            scope["__raw_tearDown__"] = scope.pop("tearDown")
        scope["tearDown"] = cls._stacked_tearDown

        # Modify all test* methods to time out after TEST_CASE_TIMEOUT seconds.
        timeout = scope.get("TEST_CASE_TIMEOUT", StackedSetup.TEST_CASE_TIMEOUT)
        if timeout is not None:
            for name, func in scope.items():
                if name.startswith("test") and hasattr(func, "__call__"):
                    # pylint: disable-next=line-too-long
                    wrapper = timeout_util.TimeoutDecorator(timeout)  # type: ignore[no-untyped-call]
                    scope[name] = wrapper(func)

        return type.__new__(cls, clsname, bases, scope)

    @staticmethod
    def _walk_mro_stacking(obj: Any, attr: Any, reverse: bool = False) -> Any:
        """Walk the stacked classes (python method resolution order)"""
        iterator = iter if reverse else reversed
        methods = (
            getattr(x, attr, None)
            for x in iterator(obj.__class__.__mro__)  # type: ignore[operator]
        )
        seen = set()
        for method in (x for x in methods if x):
            method = getattr(method, "im_func", method)
            if method not in seen:
                seen.add(method)
                yield method

    @staticmethod
    def _stacked_setUp(obj: Any) -> None:
        """Run all the setUp funcs; if any fail, run all the tearDown funcs"""
        obj.__test_was_run__ = False
        try:
            for target in StackedSetup._walk_mro_stacking(obj, "__raw_setUp__"):
                target(obj)
        except:
            # TestCase doesn't trigger tearDowns if setUp failed; thus
            # manually force it ourselves to ensure cleanup occurs.
            StackedSetup._stacked_tearDown(obj)
            raise

        # Now mark the object as fully setUp; this is done so that
        # any last minute assertions in tearDown can know if they should
        # run or not.
        obj.__test_was_run__ = True

    @staticmethod
    def _stacked_tearDown(obj: Any) -> None:
        """Run all tearDown funcs; if any fail, we move on to the next one."""
        exc_info = None
        for target in StackedSetup._walk_mro_stacking(
            obj, "__raw_tearDown__", True
        ):
            # pylint: disable=bare-except
            try:
                target(obj)
            except:
                # Preserve the exception, throw it after running
                # all tearDowns; we throw just the first also.  We suppress
                # pylint's warning here since it can't understand that we're
                # actually raising the exception, just in a nonstandard way.
                if exc_info is None:
                    exc_info = sys.exc_info()

        if exc_info:
            # Chuck the saved exception, w/ the same TB from
            # when it occurred.
            raise exc_info[1].with_traceback(  # type: ignore[union-attr]
                exc_info[2]
            )


class EasyAttr(Dict[Any, Any]):
    """Convenient class for simulating objects with attributes in tests.

    An EasyAttr object can be created with any attributes initialized very
    easily.  Examples:

    1) An object with .id=45 and .name="Joe":
    testobj = EasyAttr(id=45, name="Joe")
    2) An object with .title.text="Big" and .owner.text="Joe":
    testobj = EasyAttr(title=EasyAttr(text="Big"), owner=EasyAttr(text="Joe"))
    """

    __slots__ = ()

    def __getattr__(self, attr: str) -> Any:
        try:
            return self[attr]
        except KeyError:
            raise AttributeError(attr)

    def __delattr__(self, attr: str) -> None:
        try:
            self.pop(attr)
        except KeyError:
            raise AttributeError(attr)

    def __setattr__(self, attr: str, value: Any) -> None:
        self[attr] = value

    def __dir__(self) -> List[Any]:
        return list(self.keys())


class LogFilter(logging.Filter):
    """A simple log filter that intercepts log messages and stores them."""

    def __init__(self) -> None:
        logging.Filter.__init__(self)
        self.messages = io.StringIO()

    def filter(self, record: logging.LogRecord) -> bool:
        self.messages.write(record.getMessage() + "\n")
        # Return False to prevent the message from being displayed.
        return False


class LoggingCapturer:
    """Captures all messages emitted by the logging module."""

    def __init__(
        self, logger_name: str = "", log_level: int = logging.DEBUG
    ) -> None:
        self._log_filter = LogFilter()
        self._old_level: Optional[Union[int, str]] = None
        self._log_level: Union[int, str] = log_level
        self.logger_name = logger_name

    # Annotating function signature with LoggingCapturer is not synctactically
    # correct, so ignoring return type. In Python 3.11+, can use typing.Self
    # instead.
    def __enter__(self) -> LoggingCapturer:
        self.StartCapturing()
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[types.TracebackType],
    ) -> None:
        self.StopCapturing()

    def StartCapturing(self) -> None:
        """Begin capturing logging messages."""
        logger = logging.getLogger(self.logger_name)
        self._old_level = logger.getEffectiveLevel()
        logger.setLevel(self._log_level)
        logger.addFilter(self._log_filter)

    def StopCapturing(self) -> None:
        """Stop capturing logging messages."""
        logger = logging.getLogger(self.logger_name)
        logger.setLevel(self._old_level)  # type: ignore[arg-type]
        logger.removeFilter(self._log_filter)

    @property
    def messages(self) -> str:
        return self._log_filter.messages.getvalue()

    def LogsMatch(self, regex: Union[str, re.Pattern[str]]) -> bool:
        """Checks whether the logs match a given regex."""
        match = re.search(regex, self.messages, re.MULTILINE)
        return match is not None

    def LogsContain(self, msg: str) -> bool:
        """Checks whether the logs contain a given string."""
        return self.LogsMatch(re.escape(msg))


class TestCase(unittest.TestCase, metaclass=StackedSetup):
    """Basic chromite test case.

    Provides setUp/tearDown logic so that tearDown is correctly cleaned up.

    Takes care of saving/restoring process-wide settings like the environment so
    that sub-tests don't have to worry about gettings this right.

    Also includes additional assert helpers beyond python stdlib.
    """

    # The default diff is limited to 8 rows (of 80 cols).  Make this unlimited
    # so we always see the output.  If it's too much, people can use loggers or
    # pagers to scroll.
    maxDiff = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        unittest.TestCase.__init__(self, *args, **kwargs)
        # This is set to keep pylint from complaining.
        self.__test_was_run__ = False

    @staticmethod
    def _CheckTestEnv(msg: str) -> None:
        """Sanity check the environment.  https://crbug.com/1015450"""
        # Note: We use print+sys.exit here instead of logging/Die because it
        # might cause errors in tests that expect their own setUp to run before
        # their own tearDown executes.  By failing in the core funcs, we violate
        # that.
        st = os.stat("/")
        if st.st_mode & 0o007 != 0o005:
            print(
                "%s %s\nError: The root directory has broken permissions: %o\n"
                "Fix with: sudo chmod o+rx-w /"
                % (sys.argv[0], msg, st.st_mode),
                file=sys.stderr,
            )
            sys.exit(1)
        if st.st_uid or st.st_gid:
            print(
                "%s %s\nError: The root directory has broken ownership: %i:%i"
                " (should be 0:0)\nFix with: sudo chown 0:0 /"
                % (sys.argv[0], msg, st.st_uid, st.st_gid),
                file=sys.stderr,
            )
            sys.exit(1)

    def setUp(self) -> None:
        self._CheckTestEnv("%s.setUp" % (self.id(),))

        self.__saved_cwd__ = os.getcwd()
        self.__saved_umask__ = os.umask(0o22)

        self.__global_config_patchers__ = [
            mock.patch.object(
                cros_build_lib, "GetDefaultBoard", return_value=None
            ),
            mock.patch.object(
                portage_util,
                "_GetSysrootTool",
                side_effect=lambda tool, board, sysroot: (
                    f"{tool}-{board}" if board else tool
                ),
            ),
        ]
        for p in self.__global_config_patchers__:
            p.start()

    def tearDown(self) -> None:
        self._CheckTestEnv("%s.tearDown" % (self.id(),))

        os.chdir(self.__saved_cwd__)
        os.umask(self.__saved_umask__)

        try:
            memoize.SafeRun(
                [p.stop for p in self.__global_config_patchers__]
                + [mock.patch.stopall]
            )
        except RuntimeError:
            # "stop called on unstarted patcher".
            pass

    def id(self) -> str:
        """Return a name that can be passed in via the command line."""
        return "%s.%s" % (self.__class__.__name__, self._testMethodName)

    def __str__(self) -> str:
        """Return a pretty name that can be passed in via the command line."""
        return "[%s] %s" % (self.__module__, self.id())

    def assertRaises2(
        self,
        exception: Type[BaseException],
        functor: Callable[[Any], Any],
        *args: Any,
        **kwargs: Any,
    ) -> BaseException:
        """Like assertRaises, just with checking of the exception.

        Args:
            exception: The expected exception type to intecept.
            functor: The function to invoke.
            *args: Positional args to pass to the function.
            **kwargs: Optional args to pass to the function.  Note we pull
                exact_kls, msg, and check_attrs from these kwargs.
            exact_kls: If given, the exception raise must be *exactly* that
                class type; derivatives are a failure.
            check_attrs: If given, a mapping of attribute -> value to assert on
                the resultant exception.  Thus if you wanted to catch a ENOENT,
                you would do:
                    assertRaises2(EnvironmentError, func, args,
                                  check_attrs={'errno': errno.ENOENT})
            ex_msg: A substring that should be in the stringified exception.
            msg: The error message to be displayed if the exception isn't
                raised. If not given, a suitable one is defaulted to.
            returns: The exception object.
        """
        exact_kls = kwargs.pop("exact_kls", None)
        check_attrs = kwargs.pop("check_attrs", {})
        ex_msg = kwargs.pop("ex_msg", None)
        msg = kwargs.pop("msg", None)
        if msg is None:
            msg = "%s(*%r, **%r) didn't throw an exception" % (
                functor.__name__,
                args,
                kwargs,
            )
        try:
            functor(*args, **kwargs)
            raise AssertionError(msg)
        except exception as e:
            if ex_msg:
                self.assertIn(ex_msg, str(e))
            if exact_kls:
                self.assertEqual(e.__class__, exception)
            bad = []
            for attr, required in check_attrs.items():
                self.assertTrue(
                    hasattr(e, attr), msg="%s lacks attr %s" % (e, attr)
                )
                value = getattr(e, attr)
                if value != required:
                    bad.append(
                        "%s attr is %s, needed to be %s"
                        % (attr, value, required)
                    )
            if bad:
                raise AssertionError("\n".join(bad))
            return e

    def assertExists(
        self, path: Union[str, "os.PathLike[str]"], msg: Optional[str] = None
    ) -> None:
        """Make sure |path| exists"""
        if os.path.exists(path):
            return

        if msg is None:
            messages: List[str] = ["path is missing: %s" % path]
            while path != "/":
                path = os.path.dirname(path)
                if not path:
                    # If we're given something like "foo", abort once we get to
                    # "".
                    break
                result = os.path.exists(path)
                messages.append("\tos.path.exists(%s): %s" % (path, result))
                if result:
                    messages.append("\tcontents: %r" % os.listdir(path))
                    break
            msg = "\n".join(messages)

        raise self.failureException(msg)

    def assertNotExists(
        self, path: Union[str, "os.PathLike[str]"], msg: Optional[str] = None
    ) -> None:
        """Make sure |path| does not exist"""
        if not os.path.exists(path):
            return

        if msg is None:
            msg = "path exists when it should not: %s" % (path,)

        raise self.failureException(msg)

    def assertStartsWith(
        self, s: str, prefix: str, msg: Optional[str] = None
    ) -> None:
        """Asserts that |s| starts with |prefix|.

        This function should be preferred over assertTrue(s.startswith(prefix))
        for it produces better error failure message than the other.
        """
        if s.startswith(prefix):
            return

        if msg is None:
            msg = "%s does not start with %s" % (s, prefix)

        raise self.failureException(msg)

    def assertEndsWith(
        self, s: str, suffix: str, msg: Optional[str] = None
    ) -> None:
        """Asserts that |s| ends with |suffix|.

        This function should be preferred over assertTrue(s.endswith(suffix))
        for it produces better error failure message than the other.
        """
        if s.endswith(suffix):
            return

        if msg is None:
            msg = "%s does not end with %s" % (s, suffix)

        raise self.failureException(msg)

    # Upstream deprecated these in Python 3, but left them in Python 2.
    # Deprecate them ourselves to help with migration.  We can delete these
    # once upstream drops them.
    # pylint: disable-next=no-self-argument
    def _disable(  # type: ignore[misc] # complaining about no self argument
        deprecated: str, replacement: str
    ) -> Any:
        def disable_func(*_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError(
                "%s() is removed in Python 3; use %s() instead"
                % (deprecated, replacement)
            )

        return disable_func

    assertDictContainsSubset = _disable(
        "assertDictContainsSubset", "assertGreaterEqual"
    )
    assertEquals = _disable("assertEquals", "assertEqual")
    assertNotEquals = _disable("assertNotEquals", "assertNotEqual")
    assertAlmostEquals = _disable("assertAlmostEquals", "assertAlmostEqual")
    assertNotAlmostEquals = _disable(
        "assertNotAlmostEquals", "assertNotAlmostEqual"
    )
    assert_ = _disable("assert_", "assertTrue")
    failUnlessEqual = _disable("failUnlessEqual", "assertEqual")
    failIfEqual = _disable("failIfEqual", "assertNotEqual")
    failUnlessAlmostEqual = _disable(
        "failUnlessAlmostEqual", "assertAlmostEqual"
    )
    failIfAlmostEqual = _disable("failIfAlmostEqual", "assertNotAlmostEqual")
    failUnless = _disable("failUnless", "assertTrue")
    failUnlessRaises = _disable("failUnlessRaises", "assertRaises")
    failIf = _disable("failIf", "assertFalse")

    assertItemsEqual = _disable("assertItemsEqual", "assertCountEqual")
    assertRaisesRegexp = _disable("assertRaisesRegexp", "assertRaisesRegex")
    assertRegexpMatches = _disable("assertRegexpMatches", "assertRegex")


class LoggingTestCase(TestCase):
    """Base class for logging capturer test cases."""

    def AssertLogsMatch(
        self,
        log_capturer: LoggingCapturer,
        regex: Union[str, re.Pattern[str]],
        inverted: bool = False,
    ) -> None:
        """Verifies a regex matches the logs."""
        assert_msg = "%r not found in %r" % (regex, log_capturer.messages)
        assert_fn = self.assertTrue
        if inverted:
            assert_msg = "%r found in %r" % (regex, log_capturer.messages)
            assert_fn = self.assertFalse

        assert_fn(log_capturer.LogsMatch(regex), msg=assert_msg)

    def AssertLogsContain(
        self, log_capturer: LoggingCapturer, msg: str, inverted: bool = False
    ) -> None:
        """Verifies a message is contained in the logs."""
        # self.assertTrue returns NoneType
        self.AssertLogsMatch(log_capturer, re.escape(msg), inverted=inverted)


class TempDirTestCase(TestCase):
    """Mixin used to give each test a tempdir that is cleansed upon finish"""

    # Whether to delete tempdir used by this test. cf: SkipCleanup.
    DELETE: bool = True
    _NO_DELETE_TEMPDIR_OBJ: Optional[osutils.TempDir] = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        TestCase.__init__(self, *args, **kwargs)
        self._tempdir: Optional[Path] = None
        self._tempdir_obj: Optional[osutils.TempDir] = None

    @property
    def tempdir(self) -> Path:
        assert self._tempdir
        return self._tempdir

    @classmethod
    def SkipCleanup(cls) -> Path:
        """Leave behind tempdirs created by instances of this class.

        Calling this function ensures that all future instances will leak their
        temporary directories. Additionally, all future temporary directories
        will be created inside one top level temporary directory, so that you
        can easily blow them away when you're done.
        Currently, this function is pretty stupid. You should call it *before*
        creating any instances.

        Returns:
            Path to a temporary directory that contains all future temporary
            directories created by instances of this class.
        """
        cls.DELETE = False
        cls._NO_DELETE_TEMPDIR_OBJ = osutils.TempDir(
            prefix="chromite.test_no_cleanup",
            set_global=True,
            delete=cls.DELETE,
        )
        logging.info(
            "%s requested to SkipCleanup. Will leak %s",
            cls.__name__,
            cls._NO_DELETE_TEMPDIR_OBJ.tempdir,
        )
        # We can reasonably expect tempdir to be non-null after setup is
        # complete.
        return cls._NO_DELETE_TEMPDIR_OBJ.tempdir  # type: ignore[return-value]

    def setUp(self) -> None:
        self._tempdir_obj = osutils.TempDir(
            prefix="chromite.test", set_global=True, delete=self.DELETE
        )
        # We can reasonably expect tempdir to be non-null after setup is
        # complete.
        self._tempdir = Path(
            self._tempdir_obj.tempdir  # type: ignore[arg-type]
        )
        # We must use addCleanup here so that inheriting TestCase classes can
        # use addCleanup with the guarantee that the tempdir will be cleaned up
        # _after_ their addCleanup has run. TearDown runs before cleanup
        # functions.
        self.addCleanup(self._CleanTempDir)

    def _CleanTempDir(self) -> None:
        if self._tempdir_obj is not None:
            self._tempdir_obj.Cleanup()
            self._tempdir_obj = None
            self._tempdir = None

    def ExpectRootOwnedFiles(self) -> None:
        """Tells us that we may need to clean up root owned files."""
        if self._tempdir_obj is not None:
            self._tempdir_obj.SetSudoRm()

    def assertFileContents(
        self, file_path: Union[str, Path], content: Union[str, bytes]
    ) -> None:
        """Assert that the file contains the given content."""
        self.assertExists(file_path)
        read_content = osutils.ReadFile(file_path)
        self.assertEqual(read_content, content)

    def assertTempFileContents(
        self, file_path: Union[str, Path], content: Union[str, bytes]
    ) -> None:
        """Assert a file in the temp directory contains the given content."""
        self.assertFileContents(os.path.join(self.tempdir, file_path), content)

    def ReadTempFile(self, path: Union[str, Path]) -> Union[str, bytes]:
        """Read a given file from the temp directory.

        Args:
            path: The path relative to the temp directory to read.
        """
        return osutils.ReadFile(os.path.join(self.tempdir, path))

    def WriteTempFile(
        self, path: Union[str, Path], content: Union[str, bytes], **kwargs: Any
    ) -> None:
        """Write the given content to the temp directory

        Args:
            path: The path relative to the temp directory to write to.
            content: Content to write. May be either an iterable, or a string.
            **kwargs: Additional args to pass to osutils.WriteFile.
        """
        osutils.WriteFile(os.path.join(self.tempdir, path), content, **kwargs)


class FakeSDKCache:
    """Creates a fake SDK Cache."""

    def __init__(
        self, cache_dir: Union[str, Path], sdk_version: str = "12225.0.0"
    ) -> None:
        """Creates a fake SDK Cache.

        Args:
            cache_dir: The top level cache directory to use.
            sdk_version: The SDK Version.
        """
        self.cache_dir = cache_dir
        # Sets the SDK Version.
        self.sdk_version = sdk_version
        os.environ["%SDK_VERSION"] = sdk_version
        # Defines the path for the fake SDK Symlink Cache. (No backing tarball
        # cache is needed.)
        self.symlink_cache_path = os.path.join(
            self.cache_dir, "chrome-sdk", "symlinks"
        )
        # Creates an SDK SymlinkCache instance.
        self.symlink_cache = cache.DiskCache(self.symlink_cache_path)

    def CreateCacheReference(self, board: str, key: str) -> "os.PathLike[str]":
        """Creates the Cache Reference.

        Args:
            board: The board to use.
            key: The key of the item in the tarball cache.

        Returns:
            Path to the cache directory.
        """
        # Adds the cache path at the key.
        return self.symlink_cache.Lookup((board, self.sdk_version, key)).path


class MockTestCase(TestCase):
    """Python-mock based test case; compatible with StackedSetup"""

    def setUp(self) -> None:
        self._patchers: List[mock.Mock] = []

    def tearDown(self) -> None:
        # We can't just run stopall() by itself, and need to stop our patchers
        # manually since stopall() doesn't handle repatching.
        memoize.SafeRun(
            [p.stop for p in reversed(self._patchers)] + [mock.patch.stopall]
        )

    def StartPatcher(self, patcher: Any) -> Any:
        """Call start() on the patcher, and stop() in tearDown."""
        m = patcher.start()
        self._patchers.append(patcher)
        return m

    def PatchObject(self, *args: Any, **kwargs: Any) -> Any:
        """Create and start a mock.patch.object().

        stop() will be called automatically during tearDown.
        """
        assert args[:2] != (cros_build_lib, "run"), (
            "Do not mock cros_build_lib.run directly; use "
            "cros_test_lib.RunCommandTestCase/self.rc or "
            "self.StartPatcher/cros_test_lib.RunCommandMock instead"
        )

        assert args[:2] != (cros_build_lib, "sudo_run"), (
            "Do not mock cros_build_lib.sudo_run directly; use "
            "cros_test_lib.RunCommandTestCase/self.rc or "
            "self.StartPatcher/cros_test_lib.RunCommandMock instead"
        )
        return self.StartPatcher(mock.patch.object(*args, **kwargs))

    def PatchDict(self, *args: Any, **kwargs: Any) -> Any:
        """Create and start a mock.patch.dict().

        stop() will be called automatically during tearDown.
        """
        return self.StartPatcher(mock.patch.dict(*args, **kwargs))


# MockTestCase must be before TempDirTestCase in this inheritance order,
# because MockTestCase.StartPatcher() calls may be for PartialMocks, which
# create their own temporary directory.  The teardown for those directories
# occurs during MockTestCase.tearDown(), which needs to be run before
# TempDirTestCase.tearDown().
class MockTempDirTestCase(MockTestCase, TempDirTestCase):
    """Convenience class mixing TempDir and Mock."""


class ProgressBarTestCase(MockTestCase):
    """Test class to test the progress bar."""

    # pylint: disable=protected-access

    def setUp(self) -> None:
        self._terminal_size = self.PatchObject(
            operation.ProgressBarOperation,
            "_GetTerminalSize",
            return_value=operation._TerminalSize(100, 20),
        )
        self.PatchObject(os, "isatty", return_value=True)

    def SetMockTerminalSize(self, width: int, height: int) -> None:
        """Set mock terminal's size."""
        self._terminal_size.return_value = operation._TerminalSize(
            width, height
        )

    def AssertProgressBarAllEvents(self, output: str, num_events: int) -> None:
        """Check that the progress bar generates expected events."""
        skipped = 0
        for i in range(num_events):
            try:
                assert "%d%%" % (i * 100 // num_events) in output
            except AssertionError:
                skipped += 1

        # crbug.com/560953 It's normal to skip a few events under heavy CPU
        # load.
        self.assertLessEqual(
            skipped,
            num_events // 2,
            "Skipped %s of %s progress updates" % (skipped, num_events),
        )

        assert "100%" in output


@contextlib.contextmanager
def SetTimeZone(tz: str) -> Generator[None, None, None]:
    """Temporarily set the timezone to the specified value.

    This is needed because cros_test_lib.TestCase doesn't call time.tzset()
    after resetting the environment.
    """
    old_environ = os.environ.copy()
    try:
        os.environ["TZ"] = tz
        time.tzset()
        yield
    finally:
        osutils.SetEnvironment(old_environ)
        time.tzset()


class PopenMock(partial_mock.PartialCmdMock):
    """Provides a context where all _Popen instances are low-level mocked."""

    TARGET = "chromite.lib.cros_build_lib._Popen"
    ATTRS = ("__init__",)
    DEFAULT_ATTR = "__init__"

    def __init__(self) -> None:
        partial_mock.PartialCmdMock.__init__(self, create_tempdir=True)

    def _target__init__(
        self, inst: str, cmd: List[str], *args: Any, **kwargs: Any
    ) -> None:
        result = self._results["__init__"].LookupResult(
            (cmd,),
            hook_args=(
                inst,
                cmd,
            )
            + args,
            hook_kwargs=kwargs,
        )

        script = os.path.join(str(self.tempdir), "mock_cmd.sh")
        stdout = os.path.join(str(self.tempdir), "output")
        stderr = os.path.join(str(self.tempdir), "error")

        # This encoding handling might appear a bit wonky, but it's OK, I
        # promise. The purpose of this mock is to stuff data into files so that
        # we can run a fake script in place of the real command.  So any
        # cros_build_lib.run() settings will still be fully checked including
        # encoding.  This code just takes care of writing the data from
        # AddCmdResult objects.  The data might be specified in strings or in
        # bytes, and for easier typing enforcement with osutils, we decode any
        # bytestrings as of 2023.
        def _MaybeEncode(src: Union[str, bytes]) -> bytes:
            return src.encode("utf-8") if isinstance(src, str) else src

        osutils.WriteFile(stdout, _MaybeEncode(result.stdout), mode="wb")
        osutils.WriteFile(stderr, _MaybeEncode(result.stderr), mode="wb")
        osutils.WriteFile(
            script,
            [
                "#!/bin/bash\n",
                "cat %s\n" % stdout,
                "cat %s >&2\n" % stderr,
                "exit %s" % result.returncode,
            ],
            chmod=0o700,
        )
        kwargs["cwd"] = self.tempdir
        kwargs.pop("executable", None)
        self.backup["__init__"](inst, [script, "--"] + cmd, *args, **kwargs)


class RunCommandMock(partial_mock.PartialCmdMock):
    """Provides a context where all run invocations low-level mocked."""

    TARGET = "chromite.lib.cros_build_lib"
    ATTRS = ("run",)
    DEFAULT_ATTR = "run"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._called = False

    @property
    def called(self) -> bool:
        return self._called

    def run(
        self,
        cmd: Iterable[Union[str, "os.PathLike[str]"]],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        # NB: Keep in sync with PartialCmdMock.AddCmdResult.
        if isinstance(cmd, (tuple, list)):
            cmd = [str(x) if isinstance(x, os.PathLike) else x for x in cmd]
        self._called = True
        result = self._results["run"].LookupResult(
            (cmd,), kwargs=kwargs, hook_args=(cmd,) + args, hook_kwargs=kwargs
        )

        popen_mock = PopenMock()
        popen_mock.AddCmdResult(
            partial_mock.Ignore(),
            result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
        with popen_mock:
            return self.backup["run"](cmd, *args, **kwargs)

    # Backwards compat API.
    RunCommand = run


class RunCommandTestCase(MockTestCase):
    """MockTestCase that mocks out run by default."""

    def setUp(self) -> None:
        self.rc = self.StartPatcher(RunCommandMock())
        self.rc.SetDefaultCmdResult()
        self.assertCommandCalled = self.rc.assertCommandCalled
        self.assertCommandContains = self.rc.assertCommandContains

        # These ENV variables affect run behavior, hide them.
        self._old_envs = {
            e: os.environ.pop(e)
            for e in constants.ENV_PASSTHRU
            if e in os.environ
        }

    def tearDown(self) -> None:
        # Restore hidden ENVs.
        if hasattr(self, "_old_envs"):
            os.environ.update(self._old_envs)


class RunCommandTempDirTestCase(RunCommandTestCase, TempDirTestCase):
    """Convenience class mixing TempDirTestCase and RunCommandTestCase"""


class FakeCliCommand(command.CliCommand):
    """Test-only CliCommand subclass with an empty Run() method.

    This class is intended to be used in unit tests that require a CliCommand,
    but do not care about the Run() method's implementation. This CliCommand
    subclass is necessary because CliCommand is an abstract base class with an
    abstract Run() method, and thus, cannot be instantiated directly.
    """

    def Run(self) -> None:
        pass
