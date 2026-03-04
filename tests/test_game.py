import unittest

from gomoku_lan.model.game import BOARD_SIZE, GameState, check_winner


class GameTests(unittest.TestCase):
    def test_check_winner_horizontal(self) -> None:
        g = GameState.new(next_peer_id="p")
        y = 7
        for x in range(5):
            g.board[y][x] = 1
        self.assertEqual(check_winner(g.board, 4, y), 1)

    def test_check_winner_diagonal(self) -> None:
        g = GameState.new(next_peer_id="p")
        for i in range(5):
            g.board[i][i] = 2
        self.assertEqual(check_winner(g.board, 4, 4), 2)

    def test_can_place_bounds(self) -> None:
        g = GameState.new(next_peer_id="p")
        self.assertFalse(g.can_place(-1, 0))
        self.assertFalse(g.can_place(0, -1))
        self.assertFalse(g.can_place(BOARD_SIZE, 0))
        self.assertFalse(g.can_place(0, BOARD_SIZE))
        self.assertTrue(g.can_place(0, 0))
        g.board[0][0] = 1
        self.assertFalse(g.can_place(0, 0))


if __name__ == "__main__":
    unittest.main()

