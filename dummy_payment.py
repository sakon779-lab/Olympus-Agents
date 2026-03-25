class PaymentGateway:
    def process_credit_card(self, amount: float):
        """ระบบตัดบัตรเครดิตแบบจำลอง สำหรับเทสต์ระบบ CI/CD"""
        print(f"Processing payment of {amount} THB")
        return True