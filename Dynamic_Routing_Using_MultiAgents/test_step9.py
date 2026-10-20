"""Step 9 UX contract tests for backend device and link management."""
import unittest
from server import Project

class Step9Tests(unittest.TestCase):
    def setUp(self):
        self.project=Project()

    def test_add_delete_pc_and_connected_link(self):
        self.project.apply({'op':'add_device','kind':'PC','name':'PC2','x':700,'y':385})
        self.project.apply({'op':'connect','a':'SW1','b':'PC2','delay':2,'bandwidth':100})
        self.assertIn('PC2',self.project.network.devices)
        self.project.apply({'op':'remove_device','name':'PC2'})
        self.assertNotIn('PC2',self.project.network.devices)
        self.assertFalse(any('PC2' in (l.a,l.b) for l in self.project.network.links.values()))

    def test_add_pc_routing_through_switch(self):
        self.project.apply({'op':'add_device','kind':'PC','name':'PC2'})
        self.project.apply({'op':'connect','a':'SW1','b':'PC2','delay':2,'bandwidth':100})
        result=self.project.apply({'op':'preview','source':'PC1','target':'PC2'})
        self.assertEqual(result['state']['latest']['route'],['PC1','SW1','PC2'])

    def test_server_does_not_forward_transit_traffic(self):
        self.project.apply({'op':'add_device','kind':'PC','name':'PC2'})
        self.project.apply({'op':'connect','a':'S1','b':'PC2','delay':2,'bandwidth':100})
        result=self.project.apply({'op':'preview','source':'PC1','target':'PC2'})
        self.assertIsNone(result['state']['latest']['route'])

    def test_delete_connection(self):
        self.project.apply({'op':'remove_link','a':'PC1','b':'SW1'})
        self.assertFalse(any({l.a,l.b}=={'PC1','SW1'} for l in self.project.network.links.values()))

if __name__=='__main__': unittest.main()
