class PaymentGateway:
    def process_credit_card(self, amount: float):
        """ระบบตัดบัตรเครดิตแบบจำลอง สำหรับเทสต์ระบบ CI/CD"""
        print(f"Processing payment of {amount} THB")
        return True
    
    def process_bank_transfer(self, amount: float, bank_code: str):
        """ระบบโอนเงินผ่านธนาคารแบบจำลอง"""
        print(f"Transfering {amount} THB to bank {bank_code}")
        return {"status": "success", "transaction_id": f"BT{hash(amount) % 10000}"}
    
    def process_promptpay(self, phone_number: str, amount: float):
        """ระบบพร้อมเพย์แบบจำลอง"""
        print(f"PromptPay payment of {amount} THB to {phone_number}")
        return {"status": "completed", "ref_code": f"PP{hash(phone_number) % 1000}"}
    
    def refund_payment(self, transaction_id: str, amount: float):
        """ระบบคืนเงินแบบจำลอง"""
        print(f"Refunding {amount} THB for transaction {transaction_id}")
        return {"status": "refunded", "refund_id": f"RF{hash(transaction_id) % 500}"}
    
    def check_payment_status(self, transaction_id: str):
        """ตรวจสอบสถานะการชำระเงิน"""
        print(f"Checking status for transaction {transaction_id}")
        return {"transaction_id": transaction_id, "status": "completed", "amount": 100.0}
    
    def verify_payment_method(self, method: str):
        """ตรวจสอบวิธีการชำระเงิน"""
        valid_methods = ["credit_card", "bank_transfer", "promptpay", "wallet"]
        is_valid = method in valid_methods
        print(f"Validating payment method: {method}")
        return {"method": method, "is_valid": is_valid}