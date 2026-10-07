import unittest
import villa_rental_demand_search as r
class T(unittest.TestCase):
    def test_ru(self): self.assertEqual("3+1",r.classify("Ищу виллу 3+1 в аренду в Кирении"))
    def test_tr(self): self.assertEqual("4+1",r.classify("Girne'de 4+1 villa kiralamak istiyorum"))
    def test_en(self): self.assertEqual("3+1",r.classify("Looking for a 3+1 villa to rent in North Cyprus"))
    def test_sale_reject(self): self.assertIsNone(r.classify("Satılık 4+1 villa Girne"))
    def test_supply_reject(self): self.assertIsNone(r.classify("For rent 3+1 villa in Kyrenia £1500"))
if __name__=="__main__":unittest.main()
