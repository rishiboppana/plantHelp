import unittest
from src.convgraph import ConvGraph


class ConvGraphTests(unittest.TestCase):
    def graph(self):
        g = ConvGraph()
        p = g.add_node("plant", "Monstera (confidence high)", 1)
        s = g.add_node("symptom", "yellow lower leaves", 1)
        w = g.add_node("fact", "User waters every Sunday with 200ml", 1)
        a = g.add_node("advice", "Let the top 3cm of soil dry before watering", 2)
        g.add_edge(p, s, "shows"); g.add_edge(w, s, "caused by"); g.add_edge(a, s, "answers")
        return g

    def test_dedupes_nodes(self):
        g = self.graph(); n = len(g.nodes)
        g.add_node("fact", "user waters every sunday with 200ml", 3)
        self.assertEqual(len(g.nodes), n)

    def test_retrieves_matching_fact_and_core(self):
        facts, ids = self.graph().retrieve("how much water do I give on Sunday?")
        self.assertIn("200ml", facts); self.assertIn("Monstera", facts)

    def test_budget_caps_output(self):
        facts, ids = self.graph().retrieve("watering", budget=20)
        self.assertLessEqual(len(ids), 3)

    def test_roundtrip(self):
        g = self.graph(); h = ConvGraph.from_dict(g.to_dict())
        self.assertEqual(g.retrieve("water")[0], h.retrieve("water")[0])


if __name__ == "__main__":
    unittest.main()
