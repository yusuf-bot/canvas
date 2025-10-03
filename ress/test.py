import streamlit as st
import os
from google import genai
from google.genai import types
import PyPDF2
import docx
import json
import re
import requests
import base64
from typing import Dict, List, Tuple
import time

# Enhanced LaTeX resume template
LATEX_TEMPLATE = r"""
\documentclass[letterpaper,11pt]{article}

\usepackage{latexsym}
\usepackage[empty]{fullpage}
\usepackage{titlesec}
\usepackage{marvosym}
\usepackage[usenames,dvipsnames]{color}
\usepackage{verbatim}
\usepackage{enumitem}
\usepackage[hidelinks]{hyperref}
\usepackage{fancyhdr}
\usepackage[english]{babel}
\usepackage{tabularx}

\pagestyle{fancy}
\fancyhf{}
\fancyfoot{}
\renewcommand{\headrulewidth}{0pt}
\renewcommand{\footrulewidth}{0pt}

\addtolength{\oddsidemargin}{-0.5in}
\addtolength{\evensidemargin}{-0.5in}
\addtolength{\textwidth}{1in}
\addtolength{\topmargin}{-.5in}
\addtolength{\textheight}{1.0in}

\urlstyle{same}
\raggedbottom
\raggedright
\setlength{\tabcolsep}{0in}

\newcommand{\resumeItem}[1]{
  \item\small{
    {#1 \vspace{-2pt}}
  }
}

\newcommand{\resumeSubheading}[4]{
  \vspace{-2pt}\item
    \begin{tabular*}{0.97\textwidth}[t]{l@{\extracolsep{\fill}}r}
      \textbf{#1} & #2 \\
      \textit{\small#3} & \textit{\small #4} \\
    \end{tabular*}\vspace{-7pt}
}

\newcommand{\resumeProjectHeading}[2]{
    \item
    \begin{tabular*}{0.97\textwidth}{l@{\extracolsep{\fill}}r}
      \small#1 & #2 \\
    \end{tabular*}\vspace{-7pt}
}

\newcommand{\resumeSubItem}[1]{\resumeItem{#1}\vspace{-4pt}}

\renewcommand\labelitemii{$\vcenter{\hbox{\tiny$\bullet$}}$}

\newcommand{\resumeSubHeadingListStart}{\begin{itemize}[leftmargin=0.15in, label={}]}
\newcommand{\resumeSubHeadingListEnd}{\end{itemize}}
\newcommand{\resumeItemListStart}{\begin{itemize}}
\newcommand{\resumeItemListEnd}{\end{itemize}\vspace{-5pt}}

\titleformat{\section}{\vspace{-4pt}\scshape\raggedright\large}{}{0em}{}[\color{black}\titlerule \vspace{-5pt}]

\begin{document}

\begin{center}
    \textbf{\Huge \scshape {name}} \\ \vspace{1pt}
    \small {phone} $|$ \href{mailto:{email}}{\underline{{email}}} $|$ 
    \href{{linkedin_url}}{{\underline{{linkedin}}}} $|$
    \href{{github_url}}{{\underline{{github}}}}
\end{center}

\section{Experience}
\resumeSubHeadingListStart
{experience_section}
\resumeSubHeadingListEnd

\section{Education}
\resumeSubHeadingListStart
{education_section}
\resumeSubHeadingListEnd

\section{Technical Skills}
\begin{itemize}[leftmargin=0.15in, label={}]
{skills_section}
\end{itemize}

\section{Projects}
\resumeSubHeadingListStart
{projects_section}
\resumeSubHeadingListEnd

\end{document}
"""

SYSTEM_PROMPT = """
You are an expert resume optimization assistant. Your job is to help users improve their resumes by analyzing them against job descriptions and generating optimized LaTeX code.

IMPORTANT INSTRUCTIONS:
1. When generating or modifying LaTeX code, always wrap it between these exact markers:
   <<<LATEX_START>>>
   [LaTeX code here]
   <<<LATEX_END>>>

2. Always include the complete LaTeX document, not just fragments.

3. When making changes, explain what you're changing and why.

4. Focus on:
   - Tailoring content to match job requirements
   - Using relevant keywords from the job description
   - Improving formatting and presentation
   - Quantifying achievements where possible
   - Removing irrelevant information

5. Maintain professional formatting and ensure the LaTeX compiles correctly.
"""

def extract_text_from_pdf(pdf_file):
    """Extract text from PDF file."""
    try:
        pdf_reader = PyPDF2.PdfReader(pdf_file)
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text()
        return text
    except Exception as e:
        st.error(f"Error reading PDF: {str(e)}")
        return ""

def extract_text_from_docx(docx_file):
    """Extract text from DOCX file."""
    try:
        doc = docx.Document(docx_file)
        text = ""
        for paragraph in doc.paragraphs:
            text += paragraph.text + "\n"
        return text
    except Exception as e:
        st.error(f"Error reading DOCX: {str(e)}")
        return ""

def parse_resume_with_ai(client, resume_text):
    """Parse resume text and extract structured information."""
    prompt = f"""
    Parse the following resume text and extract structured information in JSON format.
    Include: name, email, phone, linkedin, github, experience (array of jobs with company, title, dates, location, bullets), 
    education (array with institution, degree, dates, location), skills (array), projects (array with name, description, technologies).
    
    Resume text:
    {resume_text}
    
    Return only valid JSON without any markdown formatting or additional text.
    """
    
    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash-exp",
            contents=[
                types.Content(
                    role="user",
                    parts=[types.Part(text=prompt)]
                )
            ]
        )
        
        content = response.text
        content = re.sub(r'```json\n?', '', content)
        content = re.sub(r'\n?```', '', content)
        
        return json.loads(content)
    except Exception as e:
        st.error(f"Error parsing resume: {str(e)}")
        return None

def generate_latex_from_json(resume_data):
    """Generate LaTeX resume from parsed JSON data."""
    try:
        # Format experience section
        experience_items = []
        for exp in resume_data.get('experience', []):
            bullets = '\n'.join([f"        \\resumeItem{{{bullet}}}" for bullet in exp.get('bullets', [])])
            exp_item = f"""    \\resumeSubheading
      {{{exp.get('title', '')}}}{{{exp.get('dates', '')}}}
      {{{exp.get('company', '')}}}{{{exp.get('location', '')}}}
      \\resumeItemListStart
{bullets}
      \\resumeItemListEnd"""
            experience_items.append(exp_item)
        experience_section = '\n'.join(experience_items)
        
        # Format education section
        education_items = []
        for edu in resume_data.get('education', []):
            edu_item = f"    \\resumeSubheading{{{edu.get('institution', '')}}}{{{edu.get('dates', '')}}}{{{edu.get('degree', '')}}}{{{edu.get('location', '')}}}"
            education_items.append(edu_item)
        education_section = '\n'.join(education_items)
        
        # Format skills section
        skills = resume_data.get('skills', [])
        skills_text = ' $|$ '.join(skills) if skills else 'Python, JavaScript, SQL'
        skills_section = f"    \\small{{\\item \\textbf{{Programming Languages}}{{: {skills_text} }}}}"
        
        # Format projects section
        projects_items = []
        for proj in resume_data.get('projects', []):
            proj_item = f"""    \\resumeProjectHeading
      {{\\textbf{{{proj.get('name', '')}}} $|$ \\emph{{{proj.get('technologies', '')}}}}}{{}}
      \\resumeItemListStart
        \\resumeItem{{{proj.get('description', '')}}}
      \\resumeItemListEnd"""
            projects_items.append(proj_item)
        projects_section = '\n'.join(projects_items)
        
        # Clean and format URLs
        linkedin_url = resume_data.get('linkedin', 'https://linkedin.com/in/yourprofile')
        github_url = resume_data.get('github', 'https://github.com/yourusername')
        
        linkedin_display = linkedin_url.replace('https://linkedin.com/in/', '').replace('https://www.linkedin.com/in/', '')
        github_display = github_url.replace('https://github.com/', '').replace('https://www.github.com/', '')
        
        # Fill template
        latex_content = LATEX_TEMPLATE.format(
            name=resume_data.get('name', 'Your Name'),
            phone=resume_data.get('phone', '(000) 000-0000'),
            email=resume_data.get('email', 'your.email@example.com'),
            linkedin_url=linkedin_url,
            linkedin=linkedin_display,
            github_url=github_url,
            github=github_display,
            experience_section=experience_section,
            education_section=education_section,
            skills_section=skills_section,
            projects_section=projects_section
        )
        
        return latex_content
    except Exception as e:
        st.error(f"Error generating LaTeX: {str(e)}")
        return None

def compile_latex_to_pdf(latex_content):
    """Compile LaTeX to PDF using latex.online API."""
    try:
        url = "https://latex.online/api/compiler"
        files = {
            'file': ('main.tex', latex_content.encode('utf-8'), 'text/plain')
        }
        
        response = requests.post(url, files=files, timeout=30)
        
        if response.status_code == 200:
            return response.content
        else:
            st.error(f"LaTeX compilation failed: {response.status_code}")
            return None
            
    except requests.exceptions.Timeout:
        st.error("LaTeX compilation timed out. Please try again.")
        return None
    except Exception as e:
        st.error(f"Error compiling LaTeX: {str(e)}")
        return None

def extract_latex_from_response(text):
    """Extract LaTeX code from AI response between markers."""
    start_tag = "<<<LATEX_START>>>"
    end_tag = "<<<LATEX_END>>>"

    start_idx = text.find(start_tag)
    if start_idx == -1:
        return None

    end_idx = text.find(end_tag, start_idx)
    if end_idx == -1:
        return None

    return text[start_idx + len(start_tag):end_idx].strip()

def get_ai_response(client, user_message, resume_data, job_description=""):
    """Get AI response with context."""
    context = f"""
    SYSTEM: {SYSTEM_PROMPT}
    
    CURRENT RESUME DATA:
    {json.dumps(resume_data, indent=2)}
    
    JOB DESCRIPTION:
    {job_description if job_description else "No job description provided"}
    
    USER MESSAGE: {user_message}
    
    Please analyze and provide recommendations. If you want to generate or modify the resume, 
    use the <<<LATEX_START>>> and <<<LATEX_END>>> markers around the complete LaTeX code.
    """
    
    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash-exp",
            contents=[
                types.Content(
                    role="user",
                    parts=[types.Part(text=context)]
                )
            ]
        )
        return response.text
    except Exception as e:
        return f"Error getting AI response: {str(e)}"

def show_jd_dialog():
    """Show job description dialog."""
    with st.container():
        st.markdown("### Add Job Description")
        jd_text = st.text_area(
            "Paste job description here:",
            height=200,
            key="jd_input",
            placeholder="Paste the job description you want to optimize your resume for..."
        )
        
        col1, col2 = st.columns([1, 1])
        with col1:
            if st.button("Insert", key="insert_jd"):
                if jd_text.strip():
                    st.session_state.job_description = jd_text
                    st.session_state.show_jd_dialog = False
                    st.success("Job description added!")
                    st.rerun()
                else:
                    st.warning("Please enter a job description")
        
        with col2:
            if st.button("Close", key="close_jd"):
                st.session_state.show_jd_dialog = False
                st.rerun()

def main():
    st.set_page_config(
        page_title="AI Resume Optimizer",
        page_icon="🚀",
        layout="wide",
        initial_sidebar_state="collapsed"
    )
    
    # Custom CSS for Claude-like UI
    st.markdown("""
    <style>
    .main {
        padding: 0;
    }
    .stApp > header {
        background-color: transparent;
    }
    .stApp {
        background-color: #1a1a1a;
        color: white;
    }
    .chat-container {
        background-color: #2d2d2d;
        border-radius: 10px;
        padding: 20px;
        margin: 10px 0;
    }
    .upload-area {
        border: 2px dashed #666;
        border-radius: 10px;
        padding: 20px;
        text-align: center;
        margin: 10px 0;
        background-color: #2d2d2d;
    }
    </style>
    """, unsafe_allow_html=True)
    
    # Initialize session state
    if 'resume_data' not in st.session_state:
        st.session_state.resume_data = None
    if 'latex_content' not in st.session_state:
        st.session_state.latex_content = None
    if 'pdf_content' not in st.session_state:
        st.session_state.pdf_content = None
    if 'chat_history' not in st.session_state:
        st.session_state.chat_history = []
    if 'job_description' not in st.session_state:
        st.session_state.job_description = ""
    if 'show_jd_dialog' not in st.session_state:
        st.session_state.show_jd_dialog = False
    if 'show_upload_options' not in st.session_state:
        st.session_state.show_upload_options = False
    
    # API Key (hardcoded for demo)
    api_key = "AIzaSyASUZ5k9EcXHCzlRrbK5WRWaU472aGWgrw"
    
    try:
        client = genai.Client(api_key=api_key)
    except Exception as e:
        st.error(f"Error initializing client: {str(e)}")
        return
    
    # Main layout
    col1, col2 = st.columns([1, 1])
    
    # Left side - PDF Viewer
    with col1:
        st.markdown("### 📄 Resume Preview")
        
        if st.session_state.pdf_content:
            base64_pdf = base64.b64encode(st.session_state.pdf_content).decode('utf-8')
            pdf_display = f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="800" type="application/pdf"></iframe>'
            st.markdown(pdf_display, unsafe_allow_html=True)
        else:
            st.markdown("""
            <div class="upload-area">
                <h3>No resume uploaded yet</h3>
                <p>Upload your resume to see the preview here</p>
            </div>
            """, unsafe_allow_html=True)
    
    # Right side - Chat Interface
    with col2:
        # Header
        st.markdown("### 🚀 AI Resume Optimizer")
        
        # Plus button and upload options
        if st.button("➕ Add Content", key="add_content"):
            st.session_state.show_upload_options = not st.session_state.show_upload_options
        
        if st.session_state.show_upload_options:
            st.markdown("**Choose what to add:**")
            col_a, col_b = st.columns(2)
            
            with col_a:
                if st.button("📄 Upload Resume", key="upload_resume_btn"):
                    st.session_state.show_upload_options = False
                    st.rerun()
            
            with col_b:
                if st.button("📋 Add Job Description", key="add_jd_btn"):
                    st.session_state.show_jd_dialog = True
                    st.session_state.show_upload_options = False
                    st.rerun()
        
        # Job description dialog
        if st.session_state.show_jd_dialog:
            show_jd_dialog()
        
        # Resume upload
        if not st.session_state.show_jd_dialog:
            uploaded_resume = st.file_uploader(
                "Upload Resume (Required)",
                type=['pdf', 'docx', 'txt'],
                help="Upload your resume file",
                key="resume_uploader"
            )
            
            # Process uploaded resume
            if uploaded_resume is not None and st.session_state.resume_data is None:
                with st.spinner("Processing resume..."):
                    # Extract text based on file type
                    if uploaded_resume.type == "application/pdf":
                        resume_text = extract_text_from_pdf(uploaded_resume)
                    elif uploaded_resume.type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
                        resume_text = extract_text_from_docx(uploaded_resume)
                    else:
                        resume_text = str(uploaded_resume.read(), "utf-8")
                    
                    if resume_text:
                        # Parse resume with AI
                        st.session_state.resume_data = parse_resume_with_ai(client, resume_text)
                        
                        if st.session_state.resume_data:
                            # Generate initial LaTeX version
                            st.session_state.latex_content = generate_latex_from_json(st.session_state.resume_data)
                            st.success("Resume processed!")
                            
                            # Compile to PDF
                            if st.session_state.latex_content:
                                with st.spinner("Compiling PDF..."):
                                    st.session_state.pdf_content = compile_latex_to_pdf(st.session_state.latex_content)
                                    if st.session_state.pdf_content:
                                        st.success("PDF generated!")
                                        st.rerun()
                        else:
                            st.error("Failed to parse resume")
        
        # Show current job description if exists
        if st.session_state.job_description:
            with st.expander("📋 Current Job Description", expanded=False):
                st.text(st.session_state.job_description[:200] + "..." if len(st.session_state.job_description) > 200 else st.session_state.job_description)
        
        # Chat interface
        if st.session_state.resume_data:
            st.markdown("---")
            st.markdown("### 💬 Chat with AI")
            
            # Display chat history
            for role, message in st.session_state.chat_history[-5:]:  # Show last 5 messages
                if role == "user":
                    st.markdown(f"**You:** {message}")
                else:
                    st.markdown(f"**AI:** {message}")
            
            # Chat input
            user_input = st.text_input("Ask for recommendations...", key="chat_input")
            
            if st.button("Send", key="send_chat") and user_input:
                # Add user message to history
                st.session_state.chat_history.append(("user", user_input))
                
                # Generate AI response
                with st.spinner("Analyzing..."):
                    response = get_ai_response(
                        client, 
                        user_input, 
                        st.session_state.resume_data,
                        st.session_state.job_description
                    )
                    
                    # Check if response contains LaTeX code
                    latex_code = extract_latex_from_response(response)
                    if latex_code:
                        st.session_state.latex_content = latex_code
                        
                        # Compile to PDF
                        with st.spinner("Compiling updated PDF..."):
                            st.session_state.pdf_content = compile_latex_to_pdf(latex_code)
                    
                    st.session_state.chat_history.append(("assistant", response))
                    st.rerun()
            
            # Quick action buttons
            st.markdown("### 🚀 Quick Actions")
            
            if st.button("📊 Get Optimization Recommendations"):
                if st.session_state.job_description:
                    prompt = "Please analyze my resume against this job description and provide specific recommendations for improvements. Generate an optimized LaTeX version."
                else:
                    prompt = "Please analyze my resume and provide general recommendations for improvements. Generate an optimized LaTeX version."
                
                st.session_state.chat_history.append(("user", prompt))
                
                with st.spinner("Getting recommendations..."):
                    response = get_ai_response(
                        client, 
                        prompt, 
                        st.session_state.resume_data,
                        st.session_state.job_description
                    )
                    
                    latex_code = extract_latex_from_response(response)
                    if latex_code:
                        st.session_state.latex_content = latex_code
                        with st.spinner("Compiling optimized PDF..."):
                            st.session_state.pdf_content = compile_latex_to_pdf(latex_code)
                    
                    st.session_state.chat_history.append(("assistant", response))
                    st.rerun()
            
            # Download buttons
            if st.session_state.latex_content:
                st.download_button(
                    label="📥 Download LaTeX",
                    data=st.session_state.latex_content,
                    file_name="optimized_resume.tex",
                    mime="text/plain"
                )
            
            if st.session_state.pdf_content:
                st.download_button(
                    label="📄 Download PDF",
                    data=st.session_state.pdf_content,
                    file_name="optimized_resume.pdf",
                    mime="application/pdf"
                )
        
        else:
            st.markdown("""
            <div class="chat-container">
                <h4>Welcome to AI Resume Optimizer!</h4>
                <p>1. Click "➕ Add Content" to upload your resume</p>
                <p>2. Optionally add a job description for targeted optimization</p>
                <p>3. Chat with AI to optimize your resume</p>
                <p>4. View real-time PDF updates on the left</p>
            </div>
            """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()