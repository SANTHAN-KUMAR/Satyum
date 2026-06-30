import os
import shutil
import fitz

def generate_salary_slip(output_path: str, employer: str, employee: str, net_pay: float):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    # Using built-in standard fonts which are extremely fast
    page.insert_text((50, 50), employer, fontname="Helvetica-Bold", fontsize=16)
    page.insert_text((50, 80), "Salary Slip for February 2023", fontname="Helvetica", fontsize=12)
    page.insert_text((50, 110), f"Employee Name: {employee}", fontname="Helvetica", fontsize=11)
    
    # Pre-calculated to save any CPU overhead
    gross = net_pay * 1.2
    deductions = gross - net_pay
    
    page.insert_text((50, 160), f"Gross Pay: {gross:.2f}", fontname="Helvetica", fontsize=11)
    page.insert_text((50, 180), f"Deductions: {deductions:.2f}", fontname="Helvetica", fontsize=11)
    page.insert_text((50, 210), f"Net Pay (Take Home): {net_pay:.2f}", fontname="Helvetica-Bold", fontsize=14)
    doc.save(output_path)
    doc.close()

def generate_form_16(output_path: str, employer: str, employee: str, net_pay: float):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((50, 50), "FORM 16", fontname="Helvetica-Bold", fontsize=16)
    page.insert_text((50, 90), f"Employer: {employer}", fontname="Helvetica", fontsize=11)
    page.insert_text((50, 120), f"Employee: {employee}", fontname="Helvetica", fontsize=11)
    
    annual_gross = (net_pay * 1.2) * 12
    page.insert_text((50, 160), f"Gross Annual Salary: {annual_gross:.2f}", fontname="Helvetica", fontsize=11)
    doc.save(output_path)
    doc.close()

def main():
    base = "demo_bundles"
    if os.path.exists(base):
        shutil.rmtree(base)
    os.makedirs(base, exist_ok=True)

    # ---------------------------------------------------------
    # 1. Generate the base templates ONCE (Very CPU efficient)
    # ---------------------------------------------------------
    print("Generating base templates...")
    os.makedirs("tmp_templates", exist_ok=True)
    
    # Template A: Corpus Person (Apeiron)
    generate_salary_slip("tmp_templates/slip_apeiron.pdf", "APEIRON PROJECTS PRIVATE LIMITED", "KARNALA SANTHAN KUMAR", 580000.00)
    generate_form_16("tmp_templates/f16_apeiron.pdf", "APEIRON PROJECTS PRIVATE LIMITED", "KARNALA SANTHAN KUMAR", 580000.00)

    # Template B: User Person (Tollways)
    generate_salary_slip("tmp_templates/slip_tollways.pdf", "TOLLWAYS INFRA PROJECTS PRIVATE LIMITED", "KARNALA SANTHAN KUMAR", 200000.00)
    generate_form_16("tmp_templates/f16_tollways.pdf", "TOLLWAYS INFRA PROJECTS PRIVATE LIMITED", "KARNALA SANTHAN KUMAR", 200000.00)

    # ---------------------------------------------------------
    # 2. Build Bundles via fast file copying
    # ---------------------------------------------------------
    print("Assembling bundles...")
    
    def assemble(name, stmt, aadhaar, slip, f16):
        d = os.path.join(base, name)
        os.makedirs(d, exist_ok=True)
        if os.path.exists(stmt): shutil.copy(stmt, os.path.join(d, "bank_statement.pdf"))
        if os.path.exists(aadhaar): shutil.copy(aadhaar, os.path.join(d, "aadhaar.pdf"))
        shutil.copy(slip, os.path.join(d, "salary_slip.pdf"))
        shutil.copy(f16, os.path.join(d, "form_16.pdf"))

    # Bundle 1: Your Clean Bundle
    assemble("01_User_Tollways_Match", 
             "652591331-Canara-Bank-Statement.pdf", "aadhars/my aadhar.pdf",
             "tmp_templates/slip_tollways.pdf", "tmp_templates/f16_tollways.pdf")

    # Bundle 2: Corpus Clean Bundle
    assemble("02_Corpus_Clean_Match", 
             "samples/real_corpus/canara_direct/genuine.pdf", "samples/real_corpus/identity/aadhaar_genuine.pdf",
             "tmp_templates/slip_apeiron.pdf", "tmp_templates/f16_apeiron.pdf")

    # Bundle 3: Corpus Tampered Math (Re-uses Apeiron templates)
    assemble("03_Corpus_Tampered_Math", 
             "samples/real_corpus/canara_direct/tamper_closing_balance.pdf", "samples/real_corpus/identity/aadhaar_genuine.pdf",
             "tmp_templates/slip_apeiron.pdf", "tmp_templates/f16_apeiron.pdf")
             
    # Bundle 4: Corpus Identity Mismatch
    assemble("04_Corpus_Identity_Mismatch", 
             "samples/real_corpus/canara_direct/genuine.pdf", "samples/real_corpus/identity/aadhaar_name_mismatch.pdf",
             "tmp_templates/slip_apeiron.pdf", "tmp_templates/f16_apeiron.pdf")

    # Cleanup temp
    shutil.rmtree("tmp_templates")
    print("Done! Extremely fast file copy complete.")

if __name__ == "__main__":
    main()
