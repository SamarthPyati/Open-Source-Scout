"""
PDF generation from markdown using ReportLab.
"""
import re
from pathlib import Path
from io import BytesIO
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Preformatted,
    Table, TableStyle, PageBreak, ListFlowable, ListItem
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER


class PDFGenerator:
    """Generate PDF documents from markdown content."""
    
    def __init__(self, page_size=letter):
        """
        Initialize PDF generator.
        
        Args:
            page_size: Page size (letter or A4)
        """
        self.page_size = page_size
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()
    
    def _setup_custom_styles(self):
        """Set up custom paragraph styles."""
        # Title style
        self.styles.add(ParagraphStyle(
            name='CustomTitle',
            parent=self.styles['Title'],
            fontSize=24,
            spaceAfter=30,
            textColor=colors.HexColor('#1a1a2e')
        ))
        
        # Heading 1
        self.styles.add(ParagraphStyle(
            name='CustomH1',
            parent=self.styles['Heading1'],
            fontSize=18,
            spaceBefore=20,
            spaceAfter=12,
            textColor=colors.HexColor('#16213e')
        ))
        
        # Heading 2
        self.styles.add(ParagraphStyle(
            name='CustomH2',
            parent=self.styles['Heading2'],
            fontSize=14,
            spaceBefore=15,
            spaceAfter=8,
            textColor=colors.HexColor('#0f3460')
        ))
        
        # Heading 3
        self.styles.add(ParagraphStyle(
            name='CustomH3',
            parent=self.styles['Heading3'],
            fontSize=12,
            spaceBefore=10,
            spaceAfter=6,
            textColor=colors.HexColor('#1a1a2e')
        ))
        
        # Code style
        self.styles.add(ParagraphStyle(
            name='Code',
            parent=self.styles['Code'],
            fontName='Courier',
            fontSize=9,
            backgroundColor=colors.HexColor('#f5f5f5'),
            leftIndent=10,
            rightIndent=10,
            spaceBefore=8,
            spaceAfter=8
        ))
        
        # Body text
        self.styles.add(ParagraphStyle(
            name='CustomBody',
            parent=self.styles['Normal'],
            fontSize=10,
            spaceBefore=4,
            spaceAfter=4,
            leading=14
        ))
    
    def markdown_to_pdf(
        self,
        markdown_content: str,
        output_path: Optional[str] = None,
        title: str = "Contributor Briefing Document"
    ) -> bytes:
        """
        Convert markdown content to PDF.
        
        Args:
            markdown_content: Markdown text to convert
            output_path: Optional path to save PDF file
            title: Document title
            
        Returns:
            PDF content as bytes
        """
        buffer = BytesIO()
        
        doc = SimpleDocTemplate(
            buffer,
            pagesize=self.page_size,
            rightMargin=0.75*inch,
            leftMargin=0.75*inch,
            topMargin=0.75*inch,
            bottomMargin=0.75*inch
        )
        
        story = []
        
        # Parse markdown and build story
        story.extend(self._parse_markdown(markdown_content, title))
        
        # Build PDF
        doc.build(story)
        
        pdf_content = buffer.getvalue()
        buffer.close()
        
        # Save to file if path provided
        if output_path:
            with open(output_path, 'wb') as f:
                f.write(pdf_content)
        
        return pdf_content
    
    def _parse_markdown(self, markdown: str, title: str) -> list:
        """Parse markdown into ReportLab flowables."""
        story = []
        
        # Add title
        story.append(Paragraph(title, self.styles['CustomTitle']))
        story.append(Spacer(1, 20))
        
        lines = markdown.split('\n')
        i = 0
        in_code_block = False
        code_lines = []
        
        while i < len(lines):
            line = lines[i]
            
            # Code block handling
            if line.strip().startswith('```'):
                if in_code_block:
                    # End code block
                    code_text = '\n'.join(code_lines)
                    story.append(Preformatted(code_text, self.styles['Code']))
                    story.append(Spacer(1, 8))
                    code_lines = []
                    in_code_block = False
                else:
                    # Start code block
                    in_code_block = True
                i += 1
                continue
            
            if in_code_block:
                code_lines.append(line)
                i += 1
                continue
            
            # Headings
            if line.startswith('# '):
                text = self._escape_html(line[2:].strip())
                story.append(Paragraph(text, self.styles['CustomH1']))
            elif line.startswith('## '):
                text = self._escape_html(line[3:].strip())
                story.append(Paragraph(text, self.styles['CustomH2']))
            elif line.startswith('### '):
                text = self._escape_html(line[4:].strip())
                story.append(Paragraph(text, self.styles['CustomH3']))
            elif line.startswith('#### '):
                text = self._escape_html(line[5:].strip())
                story.append(Paragraph(f"<b>{text}</b>", self.styles['CustomBody']))
            
            # Horizontal rule
            elif line.strip() in ['---', '***', '___']:
                story.append(Spacer(1, 10))
                # Add a line
                from reportlab.platypus import HRFlowable
                story.append(HRFlowable(width="100%", thickness=1, color=colors.grey))
                story.append(Spacer(1, 10))
            
            # Bullet list
            elif line.strip().startswith('- ') or line.strip().startswith('* '):
                # Collect all list items
                list_items = []
                while i < len(lines) and (lines[i].strip().startswith('- ') or lines[i].strip().startswith('* ')):
                    item_text = lines[i].strip()[2:]
                    item_text = self._process_inline_formatting(item_text)
                    list_items.append(ListItem(Paragraph(item_text, self.styles['CustomBody'])))
                    i += 1
                
                story.append(ListFlowable(list_items, bulletType='bullet', start='•'))
                continue
            
            # Numbered list
            elif re.match(r'^\d+\.\s', line.strip()):
                list_items = []
                while i < len(lines) and re.match(r'^\d+\.\s', lines[i].strip()):
                    item_text = re.sub(r'^\d+\.\s', '', lines[i].strip())
                    item_text = self._process_inline_formatting(item_text)
                    list_items.append(ListItem(Paragraph(item_text, self.styles['CustomBody'])))
                    i += 1
                
                story.append(ListFlowable(list_items, bulletType='1'))
                continue
            
            # Blockquote
            elif line.strip().startswith('> '):
                text = self._escape_html(line.strip()[2:])
                story.append(Paragraph(
                    f"<i>{text}</i>",
                    ParagraphStyle(
                        'Quote',
                        parent=self.styles['CustomBody'],
                        leftIndent=20,
                        textColor=colors.grey
                    )
                ))
            
            # Empty line
            elif not line.strip():
                story.append(Spacer(1, 6))
            
            # Regular paragraph
            else:
                text = self._process_inline_formatting(line)
                if text.strip():
                    story.append(Paragraph(text, self.styles['CustomBody']))
            
            i += 1
        
        return story
    
    def _escape_html(self, text: str) -> str:
        """Escape HTML special characters."""
        text = text.replace('&', '&amp;')
        text = text.replace('<', '&lt;')
        text = text.replace('>', '&gt;')
        return text
    
    def _process_inline_formatting(self, text: str) -> str:
        """Process inline markdown formatting (bold, italic, code)."""
        # Escape HTML first
        text = self._escape_html(text)
        
        # Bold: **text** or __text__
        text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
        text = re.sub(r'__(.+?)__', r'<b>\1</b>', text)
        
        # Italic: *text* or _text_
        text = re.sub(r'\*(.+?)\*', r'<i>\1</i>', text)
        text = re.sub(r'_(.+?)_', r'<i>\1</i>', text)
        
        # Inline code: `text`
        text = re.sub(r'`(.+?)`', r'<font name="Courier" size="9">\1</font>', text)
        
        # Links: [text](url) - just show text
        text = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', text)
        
        return text
