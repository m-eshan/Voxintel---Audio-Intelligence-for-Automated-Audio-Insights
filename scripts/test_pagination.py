import os
import win32com.client as win32

def test_pages(docx_path):
    word = win32.gencache.EnsureDispatch('Word.Application')
    word.Visible = False
    doc = word.Documents.Open(os.path.abspath(docx_path))
    num_pages = doc.ComputeStatistics(2)
    print(f"Total pages: {num_pages}")
    
    sections = {}
    targets = [
        'BONAFIDE CERTIFICATE',
        'ACKNOWLEDGEMENT',
        'TABLE OF CONTENTS',
        'ABSTRACT',
        'CHAPTER 1',
        'CHAPTER 2',
        'CHAPTER 3',
        'CHAPTER 4',
        'CHAPTER 5',
        'CHAPTER 6',
        'REFERENCES',
        'APPENDIX'
    ]
    
    for p in doc.Paragraphs:
        # Ignore table cells
        if p.Range.Tables.Count > 0:
            continue
        txt = p.Range.Text.strip()
        for t in targets:
            if t not in sections and (txt == t or txt.startswith(t)):
                page = p.Range.Information(1)
                sections[t] = page
                
    for t in targets:
        print(f"  {t:30}: Page {sections.get(t, 'NOT FOUND')}")
        
    doc.Close(False)
    word.Quit()

if __name__ == '__main__':
    test_pages('VoxIntel_NLP_Report.docx')
