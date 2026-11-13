import tempfile
import unittest
from pathlib import Path

from sc2_probe import ProbeConfig, parse_args, validate_config


class ProbePreflightTests(unittest.TestCase):
    def test_execution_is_opt_in(self):
        args = parse_args([])
        self.assertFalse(args.execute)

    def test_missing_paths_fail_preflight(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = ProbeConfig(
                executable=root / "missing.exe",
                install_dir=root / "missing-install",
                map_path=root / "missing-map.SC2Map",
                output_dir=root / "out",
                expected_version="5.0.17",
                base_port=5000,
                startup_timeout=30,
                shutdown_timeout=10,
            )
            errors = validate_config(config)
            self.assertTrue(any("SC2 executable" in error for error in errors))
            self.assertTrue(any("installation directory" in error for error in errors))
            self.assertTrue(any("Trusted map" in error for error in errors))

    def test_invalid_port_and_timeouts_fail_preflight(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "SC2.exe"
            install = root / "install"
            map_path = root / "map.SC2Map"
            executable.write_bytes(b"")
            install.mkdir()
            map_path.write_bytes(b"map")
            config = ProbeConfig(
                executable=executable,
                install_dir=install,
                map_path=map_path,
                output_dir=root / "out",
                expected_version="5.0.17",
                base_port=65533,
                startup_timeout=0,
                shutdown_timeout=-1,
            )
            errors = validate_config(config)
            self.assertTrue(any("Base port" in error for error in errors))
            self.assertTrue(any("timeouts" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
