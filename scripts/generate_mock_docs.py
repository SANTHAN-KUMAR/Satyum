import os
import fitz  # PyMuPDF

def generate_salary_slip(output_path: str):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)  # A4 size

    # Styling
    title_font = ("Helvetica", 18)
    header_font = ("Helvetica-Bold", 12)
    normal_font = ("Helvetica", 11)

    y = 50
    # Header
    page.insert_text((50, y), "APEIRON PROJECTS PRIVATE LIMITED", fontname=title_font[0], fontsize=title_font[1])
    y += 30
    page.insert_text((50, y), "Salary Slip for the month of February 2023", fontname=header_font[0], fontsize=header_font[1])
    y += 40

    # Employee Details
    page.insert_text((50, y), "Employee Name: KARNALA SANTHAN KUMAR", fontname=normal_font[0], fontsize=normal_font[1])
    y += 20
    page.insert_text((50, y), "Employee ID: AP-1042", fontname=normal_font[0], fontsize=normal_font[1])
    y += 20
    page.insert_text((50, y), "Designation: Senior Engineer", fontname=normal_font[0], fontsize=normal_font[1])
    y += 40

    # Earnings
    page.insert_text((50, y), "Earnings", fontname=header_font[0], fontsize=header_font[1])
    page.insert_text((300, y), "Amount (INR)", fontname=header_font[0], fontsize=header_font[1])
    y += 20
    page.insert_text((50, y), "Basic Salary", fontname=normal_font[0], fontsize=normal_font[1])
    page.insert_text((300, y), "450000.00", fontname=normal_font[0], fontsize=normal_font[1])
    y += 20
    page.insert_text((50, y), "House Rent Allowance", fontname=normal_font[0], fontsize=normal_font[1])
    page.insert_text((300, y), "100000.00", fontname=normal_font[0], fontsize=normal_font[1])
    y += 20
    page.insert_text((50, y), "Special Allowance", fontname=normal_font[0], fontsize=normal_font[1])
    page.insert_text((300, y), "100000.00", fontname=normal_font[0], fontsize=normal_font[1])
    y += 30

    page.insert_text((50, y), "Gross Pay", fontname=header_font[0], fontsize=header_font[1])
    page.insert_text((300, y), "650000.00", fontname=header_font[0], fontsize=header_font[1])
    y += 40

    # Deductions
    page.insert_text((50, y), "Deductions", fontname=header_font[0], fontsize=header_font[1])
    page.insert_text((300, y), "Amount (INR)", fontname=header_font[0], fontsize=header_font[1])
    y += 20
    page.insert_text((50, y), "Provident Fund", fontname=normal_font[0], fontsize=normal_font[1])
    page.insert_text((300, y), "20000.00", fontname=normal_font[0], fontsize=normal_font[1])
    y += 20
    page.insert_text((50, y), "Income Tax (TDS)", fontname=normal_font[0], fontsize=normal_font[1])
    page.insert_text((300, y), "50000.00", fontname=normal_font[0], fontsize=normal_font[1])
    y += 30

    page.insert_text((50, y), "Total Deductions", fontname=header_font[0], fontsize=header_font[1])
    page.insert_text((300, y), "70000.00", fontname=header_font[0], fontsize=header_font[1])
    y += 40

    # Net Pay
    page.insert_text((50, y), "Net Pay (Take Home)", fontname=header_font[0], fontsize=14)
    page.insert_text((300, y), "580000.00", fontname=header_font[0], fontsize=14)
    y += 40
    
    page.insert_text((50, y), "Amount transferred via RTGS to Canara Bank on 18 Feb 2023.", fontname=normal_font[0], fontsize=10)

    doc.save(output_path)
    print(f"Generated: {output_path}")

def generate_form_16(output_path: str):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)

    title_font = ("Helvetica-Bold", 16)
    header_font = ("Helvetica-Bold", 12)
    normal_font = ("Helvetica", 11)

    y = 50
    page.insert_text((50, y), "FORM 16", fontname=title_font[0], fontsize=title_font[1])
    y += 25
    page.insert_text((50, y), "Certificate under section 203 of the Income-tax Act, 1961", fontname=normal_font[0], fontsize=normal_font[1])
    y += 40

    page.insert_text((50, y), "Name and Address of the Employer", fontname=header_font[0], fontsize=header_font[1])
    y += 20
    page.insert_text((50, y), "APEIRON PROJECTS PRIVATE LIMITED", fontname=normal_font[0], fontsize=normal_font[1])
    y += 20
    page.insert_text((50, y), "Bhubaneswar, Odisha", fontname=normal_font[0], fontsize=normal_font[1])
    y += 40

    page.insert_text((50, y), "Name and Address of the Employee", fontname=header_font[0], fontsize=header_font[1])
    y += 20
    page.insert_text((50, y), "KARNALA SANTHAN KUMAR", fontname=normal_font[0], fontsize=normal_font[1])
    y += 20
    page.insert_text((50, y), "PAN: ABCDE1234F", fontname=normal_font[0], fontsize=normal_font[1])
    y += 40

    page.insert_text((50, y), "Assessment Year", fontname=header_font[0], fontsize=header_font[1])
    page.insert_text((300, y), "2023-24", fontname=normal_font[0], fontsize=normal_font[1])
    y += 40

    page.insert_text((50, y), "Summary of Amount Paid / Credited", fontname=header_font[0], fontsize=header_font[1])
    y += 30
    page.insert_text((50, y), "Gross Salary", fontname=normal_font[0], fontsize=normal_font[1])
    page.insert_text((300, y), "7800000.00", fontname=normal_font[0], fontsize=normal_font[1])
    y += 20
    page.insert_text((50, y), "Total Exemptions", fontname=normal_font[0], fontsize=normal_font[1])
    page.insert_text((300, y), "1200000.00", fontname=normal_font[0], fontsize=normal_font[1])
    y += 20
    page.insert_text((50, y), "Taxable Income", fontname=normal_font[0], fontsize=normal_font[1])
    page.insert_text((300, y), "6600000.00", fontname=normal_font[0], fontsize=normal_font[1])
    y += 20
    page.insert_text((50, y), "Tax Deducted at Source (TDS)", fontname=normal_font[0], fontsize=normal_font[1])
    page.insert_text((300, y), "600000.00", fontname=normal_font[0], fontsize=normal_font[1])
    
    doc.save(output_path)
    print(f"Generated: {output_path}")

def main():
    os.makedirs("demo_docs", exist_ok=True)
    generate_salary_slip("demo_docs/mock_salary_slip.pdf")
    generate_form_16("demo_docs/mock_form_16.pdf")
    print("Mock documents for cross-graph verification created in 'demo_docs/'.")

if __name__ == "__main__":
    main()
