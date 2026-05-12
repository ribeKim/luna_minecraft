import unittest

from bot import rcon_command_grants_op


class RconCommandPolicyTests(unittest.TestCase):
    def test_blocks_direct_op_commands(self) -> None:
        blocked_commands = [
            "op Steve",
            "/op Steve",
            "minecraft:op Steve",
            "bukkit:op Steve",
            "OP Steve",
        ]

        for command in blocked_commands:
            with self.subTest(command=command):
                self.assertTrue(rcon_command_grants_op(command))

    def test_blocks_execute_run_op_commands(self) -> None:
        blocked_commands = [
            "execute run op Steve",
            "execute as @a run minecraft:op Steve",
            "minecraft:execute positioned 0 0 0 run bukkit:op Steve",
        ]

        for command in blocked_commands:
            with self.subTest(command=command):
                self.assertTrue(rcon_command_grants_op(command))

    def test_allows_unrelated_commands(self) -> None:
        allowed_commands = [
            "list",
            "say op Steve",
            "whitelist add Steve",
            "deop Steve",
            "execute run say op Steve",
        ]

        for command in allowed_commands:
            with self.subTest(command=command):
                self.assertFalse(rcon_command_grants_op(command))


if __name__ == "__main__":
    unittest.main()
