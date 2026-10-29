"""WHOLLY FICTIONAL modules/functions/files; no official module injection."""
from __future__ import annotations

import ast
import asyncio
import builtins
import importlib
import importlib.machinery
import importlib.util
import inspect
import json
import os
import sys
import tempfile
import types
import unittest
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from unittest import mock

import pytest

from canvas_mcp import runtime_identity as helper
from canvas_mcp.core import tool_policy as policy

integrated_helper = helper
REPO_ROOT = Path(__file__).resolve().parents[1]
HELPER = REPO_ROOT / "src/canvas_mcp/runtime_identity.py"


def missing_filesystem_capabilities(*, symlink=False):
    """Check the actual primitives the protected reader requires, not OS names.

    No filesystem probe failure is caught or converted into a skip. Once these
    advertised capabilities exist, IO/assertion failures remain real failures.
    """
    missing = [name for name in ("O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK")
               if type(getattr(os, name, None)) is not int or getattr(os, name) == 0]
    for function, name in ((os.open, "open(dir_fd)"), (os.stat, "stat(dir_fd)")):
        if function not in getattr(os, "supports_dir_fd", ()):
            missing.append(name)
    if os.stat not in getattr(os, "supports_follow_symlinks", ()):
        missing.append("stat(follow_symlinks=False)")
    if symlink and not callable(getattr(os, "symlink", None)):
        missing.append("symlink")
    return missing


def requires_safe_filesystem(*, symlink=False):
    """Runtime capability gate attached only to individual IO-dependent cases."""
    def decorate(function):
        @wraps(function)
        def checked(self, *args, **kwargs):
            missing = missing_filesystem_capabilities(symlink=symlink)
            if missing:
                self.skipTest("requires filesystem capabilities: " + ", ".join(missing))
            return function(self, *args, **kwargs)
        checked.safe_filesystem_required = True
        return checked
    return decorate


@contextmanager
def without_nofollow():
    """One process-local capability omission, restored even after assertion."""
    absent = object()
    original = getattr(os, "O_NOFOLLOW", absent)
    try:
        if original is not absent:
            del os.O_NOFOLLOW
        yield
    finally:
        if original is not absent:
            os.O_NOFOLLOW = original


@contextmanager
def normal_fictional_leaf():
    """Normal-imported fictional leaf; no official module/spec/code injection."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        name = "portability_leaf_" + root.name
        relative = name + ".py"
        (root / relative).write_text("def probe():\n    return 7\n", encoding="utf-8")
        original_path = list(sys.path)
        try:
            sys.path.insert(0, str(root))
            module = importlib.import_module(name)
            yield root, (("fixture", name, relative, ("probe",)),), {name: module}
        finally:
            sys.path[:] = original_path


class Trap:
    def __repr__(self):
        raise AssertionError("private repr touched")

    def __eq__(self, other):
        raise AssertionError("private equality touched")

    def __getitem__(self, key):
        raise AssertionError("environment/config touched")

    def get(self, *args):
        raise AssertionError("environment/config touched")

    def __iter__(self):
        raise AssertionError("private enumeration touched")


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.relative = "src/fictional/alpha.py"
        self.file = self.root / self.relative
        self.file.parent.mkdir(parents=True)
        self.module_name = "fictional.alpha"
        self.targets = (("fixture", self.module_name, self.relative, ("probe",)),)
        self.module = self.load("def probe():\n    return 'FICTIONAL_OLD'\n")
        self.loaded = {self.module_name: self.module}
        self.metadata = self.root / helper._DIST_REL
        self.metadata.parent.mkdir(parents=True)
        self.metadata.write_text("Metadata-Version: 2.4\nName: canvas-mcp\nVersion: 1.16.0\n\nFICTIONAL DESCRIPTION\n", encoding="utf-8")

    def load(self, source):
        self.file.write_text(source, encoding="utf-8")
        module = types.ModuleType(self.module_name)
        module.__file__ = str(self.file)
        module.__spec__ = importlib.machinery.ModuleSpec(self.module_name, None, origin=str(self.file))
        exec(compile(source, str(self.file), "exec"), module.__dict__)
        return module

    def observe(self, targets=None, loaded=None):
        return helper._collect(self.root, self.targets if targets is None else targets,
                               self.loaded if loaded is None else loaded)

    def target(self):
        return self.observe()["targets"][0]

    @requires_safe_filesystem()
    def test_loaded_code_and_later_disk_bytes_are_distinct(self):
        before = self.target()
        self.file.write_text("def probe():\n    return 'FICTIONAL_NEW'\n", encoding="utf-8")
        after = self.target()
        self.assertEqual(before["loaded_code_sha256"], after["loaded_code_sha256"])
        self.assertNotEqual(before["disk_source_sha256"], after["disk_source_sha256"])
        self.assertEqual(after["disk_loaded_equivalence"], "NOT_ATTESTED")

    @requires_safe_filesystem()
    def test_identical_declared_version_does_not_imply_identical_loaded_code(self):
        old = self.observe()
        self.loaded[self.module_name] = self.load("def probe():\n    return 'FICTIONAL_DIFFERENT'\n")
        new = self.observe()
        self.assertEqual(old["declared_distribution"], new["declared_distribution"])
        self.assertNotEqual(old["targets"][0]["loaded_code_sha256"], new["targets"][0]["loaded_code_sha256"])

    def test_absent_optional_module_stays_unknown_without_import(self):
        with mock.patch("builtins.__import__", side_effect=AssertionError("import attempted")):
            result = self.observe(loaded={})
        self.assertEqual(result["targets"][0]["reason"], "MODULE_NOT_LOADED")
        self.assertNotIn(self.module_name, __import__("sys").modules)

    def test_module_file_origin_mismatch_never_reads_other_path(self):
        self.module.__file__ = "/FICTIONAL_PRIVATE_DO_NOT_READ"
        result = self.target()
        self.assertEqual(result["reason"], "UNQUALIFIED_ORIGIN")
        self.assertNotIn("FICTIONAL_PRIVATE", json.dumps(result))

    def test_spec_origin_mismatch(self):
        self.module.__spec__.origin = "/FICTIONAL_OTHER"
        self.assertEqual(self.target()["reason"], "UNQUALIFIED_ORIGIN")

    def test_code_filename_mismatch(self):
        namespace = {"__name__": self.module_name}
        exec(compile("def probe():\n    return 3\n", "/FICTIONAL_OTHER", "exec"), namespace)
        self.module.probe = namespace["probe"]  # New fictional function, never an official class.
        self.assertEqual(self.target()["reason"], "UNQUALIFIED_CODE_ORIGIN")

    def test_malformed_origin_objects_do_not_run_equality_hooks(self):
        for location in ("file", "spec"):
            with self.subTest(location=location):
                module = self.load("def probe():\n    return 1\n")
                if location == "file":
                    module.__file__ = Trap()
                else:
                    module.__spec__.origin = Trap()
                result = self.observe(loaded={self.module_name: module})
                self.assertEqual(result["targets"][0]["reason"], "UNQUALIFIED_ORIGIN")

    @requires_safe_filesystem()
    def test_globals_closure_defaults_environment_and_module_hooks_untouched(self):
        module = self.load("def factory(secret):\n    def probe(default=secret):\n        return secret\n    return probe\n")
        secret = Trap()
        module.probe = module.factory(secret)
        module.private_global = secret
        module.configuration = secret
        module.__getattr__ = lambda name: (_ for _ in ()).throw(AssertionError("module hook touched"))
        with mock.patch.object(helper.os, "environ", secret):
            result = self.observe(loaded={self.module_name: module})
        self.assertEqual(result["targets"][0]["status"], "OBSERVED_SELF_REPORT")
        wire = json.dumps(result, allow_nan=False)
        self.assertNotIn(str(self.root), wire)
        self.assertNotIn("FICTIONAL DESCRIPTION", wire)

    @requires_safe_filesystem()
    def test_same_immutable_measurement_stable(self):
        self.assertEqual(self.observe(), self.observe())

    def test_original_objects_unmodified(self):
        function = self.module.probe
        original_code = function.__code__
        module_items = dict(self.module.__dict__)
        original_spec = dict(vars(self.module.__spec__))
        loaded = dict(self.loaded)
        self.observe()
        self.assertIs(function.__code__, original_code)
        self.assertEqual(self.module.__dict__, module_items)
        self.assertEqual(vars(self.module.__spec__), original_spec)
        self.assertEqual(self.loaded, loaded)

    def test_no_public_introspection_parameters(self):
        self.assertEqual(list(inspect.signature(helper.runtime_identity).parameters), [])
        for kwargs in ({"module": "fictional.alpha"}, {"path": "/FICTIONAL_PRIVATE"}, {"url": "https://invalid.invalid"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(TypeError):
                helper.runtime_identity(**kwargs)

    def test_arbitrary_or_traversing_internal_paths_rejected_without_echo(self):
        for path in ("../PRIVATE", "/PRIVATE", "src/../PRIVATE", "src//PRIVATE", "src\\PRIVATE", "src/./PRIVATE"):
            with self.subTest(path=path):
                result = self.observe(targets=(("fixture", self.module_name, path, ("probe",)),))
                self.assertEqual(result["status"], "UNKNOWN")
                self.assertNotIn("PRIVATE", json.dumps(result))

    @requires_safe_filesystem(symlink=True)
    def test_symlink_file_rejected(self):
        other = self.root / "other.py"
        other.write_text("FICTIONAL OTHER", encoding="utf-8")
        self.file.unlink()
        self.file.symlink_to(other)
        self.assertEqual(self.target()["status"], "UNKNOWN")

    @requires_safe_filesystem(symlink=True)
    def test_symlink_parent_rejected(self):
        actual = self.root / "real"
        self.file.parent.rename(actual)
        self.file.parent.symlink_to(actual, target_is_directory=True)
        self.assertEqual(self.target()["status"], "UNKNOWN")

    @requires_safe_filesystem()
    def test_oversized_disk_source_rejected(self):
        self.file.write_bytes(b"X" * (helper._MAX_SOURCE + 1))
        self.assertEqual(self.target()["reason"], "SOFTWARE_FILE_UNQUALIFIED")

    def test_missing_file_is_sanitized(self):
        self.file.unlink()
        result = self.target()
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertNotIn(str(self.root), json.dumps(result))

    @requires_safe_filesystem()
    def test_source_changed_during_bounded_read_is_held(self):
        original_read = os.read
        inode = self.file.stat().st_ino
        changed = False

        def racing_read(fd, count):
            nonlocal changed
            raw = original_read(fd, count)
            if os.fstat(fd).st_ino == inode and not changed:
                changed = True
                self.file.write_text("FICTIONAL RACE\n", encoding="utf-8")
            return raw

        with mock.patch.object(helper.os, "read", side_effect=racing_read):
            result = self.target()
        self.assertTrue(changed)
        self.assertEqual(result["reason"], "SOFTWARE_CHANGED_DURING_READ")

    @requires_safe_filesystem()
    def test_loaded_target_replaced_during_measurement_is_held(self):
        original = helper._read_software
        replacement = types.ModuleType(self.module_name)
        replacement.__file__ = str(self.file)
        replacement.__spec__ = importlib.machinery.ModuleSpec(self.module_name, None, origin=str(self.file))
        exec(compile("def probe():\n    return 9\n", str(self.file), "exec"), replacement.__dict__)

        def replace_after_read(root, relative, limit):
            raw = original(root, relative, limit)
            if relative == self.relative:
                self.loaded[self.module_name] = replacement  # Fictional map, never sys.modules.
            return raw

        with mock.patch.object(helper, "_read_software", side_effect=replace_after_read):
            result = self.target()
        self.assertEqual(result["reason"], "LOADED_TARGET_CHANGED_DURING_MEASUREMENT")

    def test_nonfinite_code_constant_is_held(self):
        self.loaded[self.module_name] = self.load("def probe():\n    return 1e999\n")
        self.assertEqual(self.target()["reason"], "NONFINITE_CODE_CONSTANT")

    def test_malformed_immutable_code_copy_does_not_invoke_object_hooks(self):
        copied_code = self.module.probe.__code__.replace(co_consts=(Trap(),))
        with self.assertRaises(helper._Hold) as error:
            helper._code_fingerprint(copied_code)
        self.assertEqual(str(error.exception), "UNSUPPORTED_CODE_CONSTANT")
        self.assertIsNot(self.module.probe.__code__, copied_code)

    def test_large_code_constants_held(self):
        self.loaded[self.module_name] = self.load("def probe():\n    return " + repr("F" * 200_001) + "\n")
        self.assertEqual(self.target()["reason"], "CODE_LIMIT")

    def test_builtin_and_descriptor_targets_are_not_introspected(self):
        for value in (len, property(lambda self: Trap()), Trap()):
            with self.subTest(kind=type(value).__name__):
                self.module.probe = value
                self.assertEqual(self.target()["reason"], "UNQUALIFIED_CALLABLE")

    @requires_safe_filesystem()
    def test_class_method_uses_static_class_dictionary_only(self):
        self.loaded[self.module_name] = self.load("class Adapter:\n    async def read(self):\n        return 4\n")
        targets = (("fixture", self.module_name, self.relative, ("Adapter", "read")),)
        self.assertEqual(self.observe(targets=targets)["targets"][0]["status"], "OBSERVED_SELF_REPORT")

    def test_metadata_absent_malformed_or_oversized_stays_unknown(self):
        for raw in (b"Name: OTHER\nVersion: 1.16.0\n", b"Name: canvas-mcp\nVersion: 1.16.0\nVersion: SECRET\n", b"X" * 65_537, b"\xff"):
            with self.subTest(size=len(raw)):
                self.metadata.write_bytes(raw)
                result = self.observe()
                self.assertEqual(result["declared_distribution"]["status"], "UNKNOWN")
                self.assertNotIn("SECRET", json.dumps(result))
        self.metadata.unlink()
        self.assertEqual(self.observe()["declared_distribution"]["status"], "UNKNOWN")

    @requires_safe_filesystem()
    def test_output_is_small_finite_and_contains_no_code_source_or_absolute_origin(self):
        result = self.observe()
        wire = json.dumps(result, allow_nan=False)
        self.assertLess(len(wire), 4096)
        for private in (str(self.root), "FICTIONAL_OLD", "FICTIONAL DESCRIPTION", "co_consts", "co_code"):
            self.assertNotIn(private, wire)
        self.assertEqual(len(result["targets"][0]["loaded_code_sha256"]), 64)

    def test_invalid_registry_is_fixed_unknown(self):
        for targets in ([self.targets[0]], (self.targets[0],) * 4, (("PRIVATE/path", self.module_name, self.relative, ("probe",)),)):
            with self.subTest(kind=type(targets).__name__):
                result = self.observe(targets=targets)
                self.assertEqual(result["reason"], "INVALID_INTERNAL_REGISTRY")
                self.assertNotIn("PRIVATE", json.dumps(result))

    def test_registration_is_shared_for_all_general_profiles(self):
        app = ast.parse((REPO_ROOT / "src/canvas_mcp/server.py").read_bytes())
        register = next(n for n in app.body if isinstance(n, ast.FunctionDef) and n.name == "register_all_tools")
        direct_calls = [n.value for n in register.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)]
        self.assertTrue(any(isinstance(n.func, ast.Name) and n.func.id == "register_discovery_tools" for n in direct_calls))
        discovery = ast.parse((REPO_ROOT / "src/canvas_mcp/tools/discovery.py").read_bytes())
        self.assertEqual(sum(isinstance(n, ast.AsyncFunctionDef) and n.name == "get_runtime_identity"
                             for n in ast.walk(discovery)), 1)

    def test_integrated_policy_classifies_new_name_explicitly_read(self):
        self.assertIs(policy.TOOL_EFFECTS["get_runtime_identity"], policy.Effect.READ)
        self.assertNotIn("get_runtime_identity", policy.SIDE_EFFECT_TOOLS)
        self.assertNotIn("get_runtime_identity", policy._ALL_KEYWORD_TOOLS)

    @requires_safe_filesystem()
    def test_exact_observed_result_field_schema_with_wholly_fictional_target(self):
        result = self.observe()
        self.assertEqual(set(result), {"schema", "attestation", "declared_distribution", "targets", "limitations"})
        self.assertEqual(result["declared_distribution"], {
            "status": "DECLARED_ON_DISK_ONLY", "name": "canvas-mcp", "version": "1.16.0",
            "origin": "registered_distribution_metadata"})
        target = result["targets"][0]
        self.assertEqual(set(target), {"target", "status", "origin", "disk_source_sha256",
                                      "loaded_code_sha256", "code_format", "disk_loaded_equivalence"})
        self.assertEqual(target["target"], "fixture")
        self.assertEqual(target["origin"], "src/fictional/alpha.py")
        self.assertEqual(target["status"], "OBSERVED_SELF_REPORT")
        self.assertEqual(target["code_format"], "CANVAS_SELECTED_CODE_V1")
        self.assertEqual(target["disk_loaded_equivalence"], "NOT_ATTESTED")
        for name in ("disk_source_sha256", "loaded_code_sha256"):
            self.assertRegex(target[name], r"^[0-9a-f]{64}$")


class FictionalAnnotations:
    """Records literal decorator kwargs; does not claim SDK schema validation."""
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class RecordingMCP:
    """Minimal public decorator/list/remove protocol; never an SDK/client shim."""
    def __init__(self):
        self.tools = {}
        self.records = {}
        self.extra_names = set()
        self.local_provider = self
        self.registration_calls = []

    def tool(self, **kwargs):
        def record(function):
            self.tools[function.__name__] = function
            signature = inspect.signature(function)
            self.records[function.__name__] = {
                "annotations": kwargs["annotations"].kwargs,
                "signature": signature,
                "protocol_input_schema": {"type": "object", "properties": {
                    name: {} for name in signature.parameters}},
            }
            return function
        return record

    async def list_tools(self, **kwargs):
        return [types.SimpleNamespace(name=name) for name in sorted(set(self.tools) | self.extra_names)]

    def remove_tool(self, name):
        self.tools.pop(name, None)
        self.extra_names.discard(name)

    @property
    def names(self):
        return set(self.tools) | self.extra_names


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = REPO_ROOT
        cls.candidate = REPO_ROOT
        cls.discovery_source = (cls.candidate / "src/canvas_mcp/tools/discovery.py").read_bytes()
        cls.discovery_ast = ast.parse(cls.discovery_source)
        cls.register_node = next(n for n in cls.discovery_ast.body
                                 if isinstance(n, ast.FunctionDef) and n.name == "register_discovery_tools")
        # Exact function body, decorators and lazy relative helper import. Only
        # surrounding SDK/validation collaborators are fictional and labelled.
        future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
        extracted = ast.fix_missing_locations(ast.Module(body=[future, cls.register_node], type_ignores=[]))
        namespace = {"__name__": "fictional_extracted_discovery_registration",
                     "__package__": "canvas_mcp.tools", "json": json,
                     "ToolAnnotations": FictionalAnnotations,
                     "validate_params": lambda function: function}
        exec(compile(extracted, str(cls.candidate / "src/canvas_mcp/tools/discovery.py"), "exec"), namespace)
        cls.register = staticmethod(namespace["register_discovery_tools"])
        cls.app_ast = ast.parse((REPO_ROOT / "src/canvas_mcp/server.py").read_bytes())
        cls.app_register_node = next(n for n in cls.app_ast.body
                                     if isinstance(n, ast.FunctionDef) and n.name == "register_all_tools")
        # Classification is runtime policy input, not a frozen staging receipt.
        # Preservation of the prior source bytes belongs to build/review evidence.
        cls.baseline_effects = {name: effect.name for name, effect in policy.TOOL_EFFECTS.items()
                                if name != "get_runtime_identity"}


    def registry(self, role="all"):
        registry = RecordingMCP()
        def stub(name):
            def record(*args, **kwargs):
                registry.registration_calls.append(name)
            return record
        names = {n.func.id for n in ast.walk(self.app_register_node)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                 and n.func.id.startswith("register_")}
        namespace = {name: stub(name) for name in names}
        def discovery(mcp):
            registry.registration_calls.append("register_discovery_tools")
            self.register(mcp)
        namespace.update(register_discovery_tools=discovery, log_info=lambda *args, **kwargs: None,
                         install_tool_result_contract=lambda *args: None,
                         get_config=lambda: types.SimpleNamespace(execute_typescript_enabled=False))
        # Fictional branch fixture only; get_config is never imported/called from
        # the application. No server/main/client construction takes place.
        future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
        extracted = ast.fix_missing_locations(ast.Module(body=[future, self.app_register_node], type_ignores=[]))
        exec(compile(extracted, "FICTIONAL_EXTRACTED_GENERAL_REGISTRATION", "exec"), namespace)
        namespace["register_all_tools"](registry, role=role)
        return registry

    def test_public_decorator_zero_argument_str_and_protocol_schema(self):
        registry = self.registry()
        record = registry.records["get_runtime_identity"]
        self.assertEqual(record["annotations"], {"read_only_hint": True})
        self.assertEqual(list(record["signature"].parameters), [])
        self.assertEqual(record["signature"].return_annotation, "str")
        self.assertEqual(record["protocol_input_schema"], {"type": "object", "properties": {}})
        self.assertEqual(set(registry.tools), {"search_canvas_tools", "get_runtime_identity"})

    def test_wrapper_fixed_schema_for_controlled_optional_unknown(self):
        # Wrapper serialization uses a controlled fictional result, independent
        # of application modules imported by other tests during collection.
        controlled = {
            "schema": "CANVAS_RUNTIME_IDENTITY_V1", "attestation": "SELF_REPORT_ONLY",
            "declared_distribution": {"status": "UNKNOWN", "reason": "DECLARED_METADATA_UNAVAILABLE_OR_UNQUALIFIED"},
            "targets": [{"target": name, "status": "UNKNOWN", "reason": "MODULE_NOT_LOADED"}
                        for name in ("canvas_server", "gradebook_server", "gradebook_google")],
            "limitations": ["SELECTED_FUNCTION_CODE_ONLY", "NO_GLOBALS_CLOSURE_DEFAULTS_OR_CLIENT_STATE",
                            "NO_DISK_LOADED_EQUIVALENCE", "NO_THIRD_PARTY_ATTESTATION_OR_READINESS"],
        }
        with mock.patch.object(integrated_helper, "runtime_identity", return_value=controlled) as measure:
            wire = asyncio.run(self.registry().tools["get_runtime_identity"]())
        measure.assert_called_once_with()
        self.assertIs(type(wire), str)
        result = json.loads(wire)
        self.assertEqual(set(result), {"schema", "attestation", "declared_distribution", "targets", "limitations"})
        self.assertEqual(result["schema"], "CANVAS_RUNTIME_IDENTITY_V1")
        self.assertEqual(result["attestation"], "SELF_REPORT_ONLY")
        self.assertEqual(result["declared_distribution"], {
            "status": "UNKNOWN", "reason": "DECLARED_METADATA_UNAVAILABLE_OR_UNQUALIFIED"})
        self.assertEqual(result["targets"], [
            {"target": name, "status": "UNKNOWN", "reason": "MODULE_NOT_LOADED"}
            for name in ("canvas_server", "gradebook_server", "gradebook_google")])
        self.assertEqual(result["limitations"], ["SELECTED_FUNCTION_CODE_ONLY",
            "NO_GLOBALS_CLOSURE_DEFAULTS_OR_CLIENT_STATE", "NO_DISK_LOADED_EQUIVALENCE",
            "NO_THIRD_PARTY_ATTESTATION_OR_READINESS"])
        self.assertLess(len(wire), 4096)

    def test_guarded_helper_import_failure_is_fixed_unknown(self):
        tool = self.registry().tools["get_runtime_identity"]
        normal_import = builtins.__import__
        def unavailable(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "runtime_identity" and level == 2:
                raise ImportError("FICTIONAL_PRIVATE_EXCEPTION_DO_NOT_EXPORT")
            return normal_import(name, globals, locals, fromlist, level)
        with mock.patch("builtins.__import__", side_effect=unavailable):
            result = json.loads(asyncio.run(tool()))
        self.assertEqual(result, {"schema": "CANVAS_RUNTIME_IDENTITY_V1", "status": "UNKNOWN",
                                  "reason": "IDENTITY_HELPER_UNAVAILABLE"})

    def test_caller_supplied_selectors_rejected_before_body(self):
        tool = self.registry().tools["get_runtime_identity"]
        for name in ("module", "path", "file", "url", "target"):
            with self.subTest(name=name), self.assertRaises(TypeError):
                tool(**{name: "FICTIONAL_REJECTED_SELECTOR"})
        with self.assertRaises(TypeError):
            tool("FICTIONAL_REJECTED_POSITIONAL")

    def test_all_three_profiles_call_shared_registration_once(self):
        for role in ("student", "educator", "all"):
            with self.subTest(role=role):
                registry = self.registry(role)
                self.assertIn("get_runtime_identity", registry.tools)
                self.assertEqual(registry.registration_calls.count("register_discovery_tools"), 1)
                self.assertEqual("register_student_tools" in registry.registration_calls, role in ("student", "all"))
                self.assertEqual("register_educator_assignment_tools" in registry.registration_calls, role in ("educator", "all"))
        direct = [n.value for n in self.app_register_node.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)]
        self.assertTrue(any(isinstance(n.func, ast.Name) and n.func.id == "register_discovery_tools" for n in direct))

    def test_actual_policy_modes_across_profiles_and_transports(self):
        modes = (None, "none", "", " , ", "all", "create_assignment",
                 "create_assignment,execute_typescript", "all create_assignment")
        baseline_reads = {name for name, effect in self.baseline_effects.items() if effect == "READ"}
        baseline_side = set(self.baseline_effects) - baseline_reads
        all_keyword = {name for name, effect in self.baseline_effects.items()
                       if effect in ("CANVAS_WRITE", "LOCAL_WRITE")}
        for role in ("student", "educator", "all"):
            for transport in ("stdio", "http"):
                for raw in modes:
                    with self.subTest(role=role, transport=transport, raw=raw):
                        registry = self.registry(role)
                        # A fictional classification corpus, not an assertion
                        # that every profile registers all side-effect tools.
                        registry.extra_names = set(self.baseline_effects) | {"fictional_unclassified"}
                        resolved = policy.resolve_tool_policy(raw, transport)
                        removed = asyncio.run(policy.apply_tool_policy(registry, resolved))
                        if raw is None and transport == "stdio":
                            expected = set(self.baseline_effects) | {"get_runtime_identity", "fictional_unclassified"}
                            self.assertFalse(resolved.enforced)
                            self.assertEqual(resolved.allowed, baseline_side)
                        else:
                            allowed = set()
                            if raw in ("all", "all create_assignment"):
                                allowed = all_keyword
                            elif raw == "create_assignment":
                                allowed = {"create_assignment"}
                            elif raw == "create_assignment,execute_typescript":
                                allowed = {"create_assignment", "execute_typescript"}
                            expected = baseline_reads | allowed | {"get_runtime_identity"}
                            self.assertTrue(resolved.enforced)
                            self.assertEqual(resolved.allowed, allowed)
                            self.assertIn("fictional_unclassified", removed)
                        self.assertEqual(registry.names, expected)
                        self.assertIn("get_runtime_identity", registry.names)
                        self.assertEqual(registry.names & set(self.baseline_effects), expected & set(self.baseline_effects))

    def test_invalid_policy_remains_rejection_before_registration(self):
        for raw in ("fictional_unclassified", "none,all", "none,create_assignment"):
            for transport in ("stdio", "http"):
                with self.subTest(raw=raw, transport=transport), self.assertRaises(policy.ToolPolicyError):
                    policy.resolve_tool_policy(raw, transport)

    def test_read_tool_names_remain_invalid_in_write_allowlist(self):
        for name in ("get_runtime_identity", "search_canvas_tools"):
            for transport in ("stdio", "http"):
                with self.subTest(name=name, transport=transport), self.assertRaisesRegex(policy.ToolPolicyError, "read-only tools"):
                    policy.resolve_tool_policy(name, transport)

    def test_classification_only_delta_and_side_effect_membership_preserved(self):
        after = {name: effect.name for name, effect in policy.TOOL_EFFECTS.items()}
        self.assertEqual(after, {**self.baseline_effects, "get_runtime_identity": "READ"})
        self.assertEqual(sum(effect == "READ" for effect in after.values()), 73)
        self.assertEqual(policy.SIDE_EFFECT_TOOLS,
                         {name for name, effect in self.baseline_effects.items() if effect != "READ"})
        self.assertEqual(policy._ALL_KEYWORD_TOOLS,
                         {name for name, effect in self.baseline_effects.items() if effect in ("CANVAS_WRITE", "LOCAL_WRITE")})

    def test_policy_preserves_reads_and_filters_unclassified(self):
        # Behavioral policy contract; exact patch-admission comparisons are external
        # build evidence and must not require a private preimage in public tests.
        registry = self.registry()
        registry.extra_names = {"fictional_unclassified", "create_assignment"}
        removed = asyncio.run(policy.apply_tool_policy(registry, policy.resolve_tool_policy("none", "http")))
        self.assertEqual(removed, ["create_assignment", "fictional_unclassified"])
        self.assertEqual(registry.names, {"search_canvas_tools", "get_runtime_identity"})

    def test_dedicated_gradebook_route_is_excluded(self):
        tree = ast.parse((REPO_ROOT / "src/canvas_mcp/gradebook/server.py").read_bytes())
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        self.assertNotIn("register_discovery_tools", names)
        self.assertNotIn("get_runtime_identity", names)

    def test_fixed_target_and_input_contract(self):
        # Public software contract, independent of checkout size or review hashes.
        self.assertEqual(integrated_helper._TARGETS, (
            ("canvas_server", "canvas_mcp.server", "src/canvas_mcp/server.py", ("create_server",)),
            ("gradebook_server", "canvas_mcp.gradebook.server", "src/canvas_mcp/gradebook/server.py", ("create_server",)),
            ("gradebook_google", "canvas_mcp.gradebook.google", "src/canvas_mcp/gradebook/google.py", ("GoogleSheets", "read_workbook")),
        ))
        self.assertEqual(integrated_helper._MAX_SOURCE, 2_000_000)
        self.assertEqual(list(inspect.signature(integrated_helper.runtime_identity).parameters), [])

    def test_handler_privacy_and_no_optional_application_imports(self):
        tool = self.registry().tools["get_runtime_identity"]
        target_names = ("canvas_mcp.server", "canvas_mcp.gradebook.server", "canvas_mcp.gradebook.google")
        before_modules = {name: sys.modules.get(name) for name in target_names}
        normal_import = builtins.__import__
        observed = []
        def track(name, globals=None, locals=None, fromlist=(), level=0):
            observed.append((name, level))
            return normal_import(name, globals, locals, fromlist, level)
        async def invoke_with_import_spy():
            # Event-loop setup may import platform stdlib modules (for example
            # Windows _socket). Observe the diagnostic body after loop setup.
            with mock.patch("builtins.__import__", side_effect=track), \
                 mock.patch.object(os, "getenv", side_effect=AssertionError("environment read")):
                return await tool()

        wire = asyncio.run(invoke_with_import_spy())
        self.assertEqual(observed, [("runtime_identity", 2)])
        for text in (str(self.root), "/Users/", "FICTIONAL_PRIVATE", "co_code", "co_consts"):
            self.assertNotIn(text, wire)
        # Other public tests may already import these modules. Invocation must
        # preserve that starting state, without importing or unloading targets.
        for name in target_names:
            self.assertIs(sys.modules.get(name), before_modules[name])

    def test_registration_does_not_construct_helper_clients_or_call_tool(self):
        with mock.patch.object(integrated_helper, "runtime_identity", side_effect=AssertionError("tool called during registration")), \
             mock.patch("canvas_mcp.core.client.make_canvas_request", side_effect=AssertionError("Canvas request")) as request:
            registry = self.registry("all")
        self.assertIn("get_runtime_identity", registry.tools)
        request.assert_not_called()

    def test_startup_policy_source_order_and_rejection_are_preserved(self):
        main = next(n for n in self.app_ast.body if isinstance(n, ast.FunctionDef) and n.name == "main")
        calls = {name: [n for n in ast.walk(main) if isinstance(n, ast.Call)
                       and isinstance(n.func, ast.Name) and n.func.id == name]
                 for name in ("resolve_tool_policy", "register_all_tools", "apply_tool_policy")}
        self.assertEqual([len(calls[name]) for name in calls], [1, 1, 1])
        self.assertLess(calls["resolve_tool_policy"][0].lineno, calls["register_all_tools"][0].lineno)
        self.assertLess(calls["register_all_tools"][0].lineno, calls["apply_tool_policy"][0].lineno)
        guarded = next(n for n in ast.walk(main) if isinstance(n, ast.Try)
                       and calls["resolve_tool_policy"][0] in list(ast.walk(n)))
        rejection = next(n for n in guarded.handlers if isinstance(n.type, ast.Name) and n.type.id == "ToolPolicyError")
        self.assertTrue(any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                            and isinstance(n.func.value, ast.Name) and n.func.value.id == "sys"
                            and n.func.attr == "exit" and len(n.args) == 1
                            and isinstance(n.args[0], ast.Constant) and n.args[0].value == 1
                            for n in ast.walk(rejection)))


POSIX_IO_CASES = frozenset({
    "test_loaded_code_and_later_disk_bytes_are_distinct",
    "test_identical_declared_version_does_not_imply_identical_loaded_code",
    "test_globals_closure_defaults_environment_and_module_hooks_untouched",
    "test_same_immutable_measurement_stable", "test_symlink_file_rejected", "test_symlink_parent_rejected",
    "test_oversized_disk_source_rejected", "test_source_changed_during_bounded_read_is_held",
    "test_loaded_target_replaced_during_measurement_is_held", "test_class_method_uses_static_class_dictionary_only",
    "test_output_is_small_finite_and_contains_no_code_source_or_absolute_origin",
    "test_exact_observed_result_field_schema_with_wholly_fictional_target",
})
PORTABILITY_OBSERVATIONS = []


class PortabilityTests(unittest.TestCase):
    @requires_safe_filesystem()
    def test_normal_imported_leaf_positive_measurement(self):
        with normal_fictional_leaf() as (root, targets, loaded):
            result = integrated_helper._collect(root, targets, loaded)
        target = result["targets"][0]
        self.assertEqual(target["status"], "OBSERVED_SELF_REPORT")
        self.assertEqual(target["disk_loaded_equivalence"], "NOT_ATTESTED")
        for name in ("disk_source_sha256", "loaded_code_sha256"):
            self.assertRegex(target[name], r"^[0-9a-f]{64}$")
        PORTABILITY_OBSERVATIONS.append({"case": "native_positive_normal_leaf", "passed": True,
                                        "actual_windows_execution": False})

    def test_missing_nofollow_fixed_unknown_nohash_and_state_restored(self):
        present = hasattr(os, "O_NOFOLLOW")
        original = getattr(os, "O_NOFOLLOW", None)
        with normal_fictional_leaf() as (root, targets, loaded):
            with without_nofollow():
                self.assertIn("O_NOFOLLOW", missing_filesystem_capabilities())
                result = integrated_helper._collect(root, targets, loaded)
            self.assertEqual(hasattr(os, "O_NOFOLLOW"), present)
            self.assertEqual(getattr(os, "O_NOFOLLOW", None), original)
            self.assertEqual(result["targets"], [{"target": "fixture", "status": "UNKNOWN",
                                                  "reason": "MEASUREMENT_UNAVAILABLE"}])
            wire = json.dumps(result, allow_nan=False)
            for private in ("sha256", str(root), "return 7", targets[0][1]):
                self.assertNotIn(private, wire)
        PORTABILITY_OBSERVATIONS.append({"case": "missing_nofollow", "fixed_unknown_no_hash": True,
                                        "process_state_restored": True, "actual_windows_execution": False})

    def test_actual_feature_sets_control_capability_gate(self):
        with without_nofollow():
            self.assertIn("O_NOFOLLOW", missing_filesystem_capabilities())
        with mock.patch.object(os, "supports_dir_fd", set(getattr(os, "supports_dir_fd", ())) - {os.open}, create=True):
            self.assertIn("open(dir_fd)", missing_filesystem_capabilities())
        with mock.patch.object(os, "supports_follow_symlinks", set(getattr(os, "supports_follow_symlinks", ())) - {os.stat}, create=True):
            self.assertIn("stat(follow_symlinks=False)", missing_filesystem_capabilities())

    def test_missing_capability_skips_exact_io_cases_and_runs_portable_cases(self):
        class AccountingResult(unittest.TestResult):
            def __init__(self):
                super().__init__()
                self.success_names = []

            def addSuccess(self, test):
                super().addSuccess(test)
                self.success_names.append((type(test).__name__, test._testMethodName))

        result = AccountingResult()
        suite = unittest.TestSuite([
            unittest.defaultTestLoader.loadTestsFromTestCase(IdentityTests),
            unittest.defaultTestLoader.loadTestsFromTestCase(IntegrationTests),
        ])
        with without_nofollow():
            suite.run(result)
        self.assertEqual(result.testsRun, 44)
        self.assertEqual(result.failures, [])
        self.assertEqual(result.errors, [])
        self.assertEqual({test._testMethodName for test, _ in result.skipped}, POSIX_IO_CASES)
        self.assertEqual(len(result.skipped), 12)
        self.assertTrue(all("O_NOFOLLOW" in reason for _, reason in result.skipped))
        self.assertEqual(sum(cls == "IntegrationTests" for cls, _ in result.success_names), 15)
        self.assertEqual(sum(cls == "IdentityTests" for cls, _ in result.success_names), 17)
        PORTABILITY_OBSERVATIONS.append({"case": "simulated_missing_nofollow_suite", "tests_run": 44,
                                        "passed": 32, "skipped": 12, "failures": 0, "errors": 0,
                                        "portable_integration_passed": 15, "portable_identity_passed": 17,
                                        "skip_names": sorted(POSIX_IO_CASES),
                                        "skip_reasons": sorted({reason for _, reason in result.skipped}),
                                        "actual_windows_execution": False})

    def test_unexpected_io_and_assertion_errors_are_not_changed_to_skips(self):
        class DeliberateGuardProbes(unittest.TestCase):
            @requires_safe_filesystem()
            def test_io_error(self):
                raise OSError("FICTIONAL_GUARD_PROBE")

            @requires_safe_filesystem()
            def test_assertion(self):
                raise AssertionError("FICTIONAL_GUARD_PROBE")

        result = unittest.TestResult()
        unittest.defaultTestLoader.loadTestsFromTestCase(DeliberateGuardProbes).run(result)
        if missing_filesystem_capabilities():
            self.assertEqual(len(result.skipped), 2)
            self.assertEqual((len(result.errors), len(result.failures)), (0, 0))
        else:
            self.assertEqual(len(result.skipped), 0)
            self.assertEqual((len(result.errors), len(result.failures)), (1, 1))
        PORTABILITY_OBSERVATIONS.append({"case": "intentional_guard_probes", "tests_run": 2,
                                        "expected_errors": len(result.errors), "expected_failures": len(result.failures),
                                        "capability_skips": len(result.skipped),
                                        "are_unresolved_suite_failures": False})

    def test_no_module_class_or_portable_test_blanket_skip(self):
        self.assertFalse(getattr(IdentityTests, "__unittest_skip__", False))
        self.assertFalse(getattr(IntegrationTests, "__unittest_skip__", False))
        gated = {name for name in unittest.defaultTestLoader.getTestCaseNames(IdentityTests)
                 if getattr(getattr(IdentityTests, name), "safe_filesystem_required", False)}
        self.assertEqual(gated, POSIX_IO_CASES)
        self.assertTrue(all(not getattr(getattr(IntegrationTests, name), "safe_filesystem_required", False)
                            for name in unittest.defaultTestLoader.getTestCaseNames(IntegrationTests)))


@pytest.fixture
def sdk_identity_tool(monkeypatch):
    from typing import Any, Literal

    from fastmcp import FastMCP
    from mcp.types import ToolAnnotations

    source = ast.parse((REPO_ROOT / "src/canvas_mcp/tools/discovery.py").read_bytes())
    registration = next(n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == "register_discovery_tools")
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    extracted = ast.fix_missing_locations(ast.Module(body=[future, registration], type_ignores=[]))
    namespace = {"__name__": "fictional_sdk_registration_context", "__package__": "canvas_mcp.tools",
                 "json": json, "ToolAnnotations": ToolAnnotations, "Any": Any,
                 "DetailLevel": Literal["names", "signatures", "full"],
                 "validate_params": lambda function: function}
    exec(compile(extracted, str(REPO_ROOT / "src/canvas_mcp/tools/discovery.py"), "exec"), namespace)
    mcp = FastMCP(name="fictional-runtime-identity-test", tasks=False)
    namespace["register_discovery_tools"](mcp)
    response = {"schema": "CANVAS_RUNTIME_IDENTITY_V1", "status": "UNKNOWN",
                "reason": "FICTIONAL_CONTROLLED_TEST_ONLY"}
    monkeypatch.setattr(integrated_helper, "runtime_identity", lambda: dict(response))
    return mcp, response


@pytest.mark.asyncio
async def test_real_sdk_empty_schema_and_read_only_annotation(sdk_identity_tool):
    mcp, _ = sdk_identity_tool
    tools = {tool.name: tool for tool in await mcp.list_tools()}
    diagnostic = tools["get_runtime_identity"]
    assert diagnostic.parameters["type"] == "object"
    assert diagnostic.parameters.get("properties", {}) == {}
    assert diagnostic.parameters.get("required", []) == []
    assert diagnostic.annotations.read_only_hint is True


@pytest.mark.asyncio
async def test_real_sdk_json_text_result_without_transport(sdk_identity_tool):
    mcp, response = sdk_identity_tool
    result = await mcp.call_tool("get_runtime_identity", {})
    assert len(result.content) == 1
    assert result.content[0].type == "text"
    assert json.loads(result.content[0].text) == response



if __name__ == "__main__":
    unittest.main(verbosity=2)
