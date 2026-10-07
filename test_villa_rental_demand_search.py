import unittest
import villa_rental_demand_search as r

class T(unittest.TestCase):
    def test_ru_house_offer(self):
        self.assertEqual("3+1", r.classify("Фамагуста, сдаётся дом 3+1 в долгосрочную аренду"))
    def test_tr_detached_offer(self):
        self.assertEqual("4+1", r.classify("Yeniboğaziçi'nde kiralık 4+1 müstakil ev, aylık £1800"))
    def test_en_detached_offer(self):
        self.assertEqual("3+1", r.classify("For rent 3+1 detached house in Iskele £1500"))
    def test_wrong_region_reject(self):
        self.assertIsNone(r.classify("Girne'de kiralık 3+1 villa £1800"))
    def test_sale_reject(self):
        self.assertIsNone(r.classify("İskele satılık 4+1 villa"))
    def test_demand_reject(self):
        self.assertIsNone(r.classify("Mağusa'da 3+1 müstakil ev kiralamak istiyorum"))

if __name__=="__main__":
    unittest.main()
