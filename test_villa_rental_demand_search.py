import unittest
import villa_rental_demand_search as r
class T(unittest.TestCase):
    def test_ru_offer(self): self.assertEqual("3+1",r.classify("Сдается вилла 3+1 в Кирении, долгосрочная аренда"))
    def test_tr_offer(self): self.assertEqual("4+1",r.classify("Girne'de kiralık 4+1 villa, aylık £2200"))
    def test_en_offer(self): self.assertEqual("3+1",r.classify("For rent 3+1 villa in North Cyprus £1800"))
    def test_sale_reject(self): self.assertIsNone(r.classify("Satılık 4+1 villa Girne"))
    def test_demand_reject(self): self.assertIsNone(r.classify("Girne'de 3+1 villa kiralamak istiyorum"))
if __name__=="__main__":unittest.main()
