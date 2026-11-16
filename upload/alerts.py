def tier(x):
    if x is None: return "نامشخص"
    if x >= 80: return "بحرانی"
    if x >= 65: return "بسیار قوی"
    if x >= 50: return "قوی"
    if x >= 35: return "هشدار اولیه"
    if x >= 25: return "مراقبت"
    return "عادی"

def classify(sell,buy):
    if sell is None or buy is None: return "داده ناکافی"
    if sell>=50 and buy>=50: return "تقابل شدید عرضه و تقاضا؛ نیازمند بررسی جذب یا غلبه فروش"
    if sell>=50: return "فشار فروش / غلبه فروشندگان"
    if buy>=50: return "فشار خرید / غلبه خریداران"
    if sell>=35: return "هشدار اولیه فروش"
    if buy>=35: return "هشدار اولیه خرید"
    if sell>=25 or buy>=25: return "مراقبت"
    return "وضعیت عادی"
