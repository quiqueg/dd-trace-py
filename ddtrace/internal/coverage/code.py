from collections import defaultdict
from collections import deque
from dis import findlinestarts
import gc
from pathlib import Path
import sys
from types import CodeType
from types import FunctionType
from types import ModuleType
import typing as t

import bitarray

from ddtrace.internal.injection import inject_hooks
from ddtrace.internal.module import BaseModuleWatchdog
from ddtrace.internal.module import register_run_module_transformer
from ddtrace.internal.module import unregister_run_module_transformer


_original_exec = exec


def collect_code_objects(code: CodeType, recursive: bool = False) -> t.Iterator[t.Tuple[CodeType, CodeType]]:
    q = deque([code])
    while q:
        c = q.popleft()
        for next_code in (_ for _ in c.co_consts if isinstance(_, CodeType)):
            if recursive:
                q.append(next_code)
            yield (next_code, c)


def get_lines(code: CodeType) -> t.Iterator[int]:
    yield from (ln for _, ln in findlinestarts(code) if ln > 0)


def functions_for_code(code: CodeType) -> t.Iterator[FunctionType]:
    yield from (_ for _ in gc.get_referrers(code) if isinstance(_, FunctionType) and _.__code__ is code)


def update_functions(code: CodeType, new_code: CodeType) -> None:
    for f in functions_for_code(code):
        f.__code__ = new_code


class CodeDiscovery:
    def __init__(self, module: ModuleType, recursive: bool = False) -> None:
        self.module = module
        self._lines: t.Dict[int, CodeType] = {}
        self._codes: t.Dict[CodeType, CodeType] = {}

        module_code = module.__dict__.pop("__code__", None)
        if module_code is None:
            return

        for code, parent in collect_code_objects(module_code, recursive):
            self._codes[code] = parent
            for ln in get_lines(code):
                self._lines[ln] = code

    def at_line(self, line: int) -> t.Tuple[CodeType, CodeType]:
        code = self._lines[line]
        return (code, self._codes[code])

    def code_objects(self) -> t.Iterator[CodeType]:
        return iter(self._codes.keys())

    # TODO: This is used to instrument nested functions. Re-enable it when
    # needed. Note that replace_in_tuple is a hack that needs to be implemented
    # using the C API.
    # def replace(self, old_code: CodeType, new_code: CodeType) -> None:
    #     self._codes[new_code] = parent = self._codes.pop(old_code)

    #     for ln in get_lines(old_code):
    #         self._lines[ln] = new_code

    #     replace_in_tuple(parent.co_consts, old_code, new_code)

    @classmethod
    def from_module(cls, module: ModuleType) -> "CodeDiscovery":
        try:
            return module.__code_discovery__
        except AttributeError:
            result = module.__code_discovery__ = cls(module)  # type: ignore[attr-defined]
            return result


def module_code_collector(code: CodeType, module: ModuleType) -> CodeType:
    # Cache the module code object on the module itself to prevent it from
    # being garbage collected. We will investigate this if and when needed.

    # TODO: Remove these hardcoded paths
    if Path(code.co_filename).resolve().is_relative_to(Path.cwd() / "starlette") or Path(
        code.co_filename
    ).resolve().is_relative_to(Path.cwd() / "tests"):
        module.__code__ = code  # type: ignore[attr-defined]

    return code


class ModuleCodeCollector(BaseModuleWatchdog):
    def __init__(self):
        super().__init__()
        self.lines = defaultdict(set)
        self.covered = defaultdict(set)
        self._collectors = []
        self._input_paths = []

        import atexit

        atexit.register(self.report)  # Quick and dirty coverage report

        # Replace the built-in exec function with our own
        __builtins__["exec"] = self._exec

    def _gen_hook_closure(self, collector, file_path, line_num):
        file_idx = collector.record_executable_line(file_path, line_num)

        def hook(_arg):
            collector.record_executed_line(file_idx, line_num)
        return hook

    @classmethod
    def add_collector(cls, collector):
        print(f"ADDING COLLECTOR {collector=}")
        cls._instance._collectors.append(collector)

    @classmethod
    def get_first_collector(cls):
        return cls._instance._collectors[0]

    @classmethod
    def add_input_path(cls, path):
        print(f"ADDING INPUT PATH {path=}")
        cls._instance._input_paths.append(path)

    # def hook(self, _arg):
    #     frame = sys._getframe(1)
    #     code = frame.f_code
    #     path = str(Path(code.co_filename).resolve().relative_to(Path.cwd()))
    #     if frame.f_lineno in self.covered[path]:
    #         # This line has already been covered
    #         return
    #
    #     # Take note of the line that was covered
    #     self.covered[path].add(frame.f_lineno)

    def report(self):
        print("COVERAGE REPORT:")
        for collector in self._collectors:
            from pprint import pprint
            pprint(collector._persisted_coverages)

    def transform(self, code: CodeType, module: ModuleType) -> CodeType:
        return module_code_collector(code, module)

    def after_import(self, module: ModuleType) -> None:
        _known_filenames_to_paths = {}
        _known_kept_paths = set()
        _known_rejected_paths = set()

        for code in CodeDiscovery.from_module(module).code_objects():
            if code.co_filename in _known_filenames_to_paths:
                path = _known_filenames_to_paths[code.co_filename]
            else:
                path = Path(code.co_filename).resolve()
                _known_filenames_to_paths[code.co_filename] = path

            if path in _known_rejected_paths:
                # print(f"KNOWN REJECTED PATH {path=}")
                return

            if path not in _known_kept_paths:
                keep_path = False
                for input_path in self._input_paths:
                    try:
                        if path.is_relative_to(input_path):
                            # print(f"KEEPING PATH {path=}")
                            keep_path = True
                            _known_kept_paths.add(path)
                            break
                    except ValueError:
                        #
                        pass

                if not keep_path:
                    # print(f"REJECT PATH {path=}")
                    _known_rejected_paths.add(path)
                    return
            # else:
                # print(f"KNOWN KEPT PATH {path=}")

            lines = set(get_lines(code))

            # self.lines[str(path.relative_to(Path.cwd()))] |= lines
            self.lines[path] |= lines

            # hooks = [(self.hook, line, None) for line in lines]

            hooks = [(self._gen_hook_closure(collector, path, line), line, None) for collector in self._collectors for line in lines]

            for f in functions_for_code(code):
                inject_hooks(f, hooks)

    def _exec(self, _object, _globals=None, _locals=None, **kwargs):
        # The pytest module loader doesn't implement a get_code method so we
        # need to intercept the loading of test modules by wrapping around the
        # exec built-in function.
        module = None
        if isinstance(_object, CodeType) and _object.co_name == "<module>":
            # Throwaway module object that we can use to pass the code object
            module = ModuleType(_globals.get("__name__", _object.co_filename), _globals.get("__doc__", None))
            module.__code__ = _object

        # Execute the module before calling the after_import hook
        _original_exec(_object, _globals, _locals, **kwargs)

        if module is not None:
            self.after_import(module)

    @classmethod
    def install(cls) -> None:
        register_run_module_transformer(module_code_collector)
        return super().install()

    @classmethod
    def uninstall(cls) -> None:
        unregister_run_module_transformer(module_code_collector)

        # Restore the original exec function
        __builtins__["exec"] = _original_exec

        return super().uninstall()
