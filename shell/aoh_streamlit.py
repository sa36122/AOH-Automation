import io
import os
import re
import json
import time
import boto3
import base64
import string
import streamlit as st

from time import perf_counter
from pandas import DataFrame, concat, read_csv, read_parquet
from langchain.prompts import PromptTemplate
# langchain.prompts.FewShotPromptTemplate
from langchain.llms.bedrock import Bedrock
from langchain.chains import LLMChain
from langchain_community.document_loaders import AmazonTextractPDFLoader

# Variables
model_id = 'anthropic.claude-v2:1'
knowledge_base_s3_bucket = "fa-aoh" # os.environ['KB_BUCKET_NAME']
aoh_document = "s3://fa-aoh/aoh2_redacted.pdf"
instruction_s3 = "s3://fa-aoh/Affidavit of Heirship_FS_All_TX_All.pdf"

# AWS Session and Clients Instantiation
session = boto3.Session(region_name=os.environ['AWS_REGION'])
agent_client = boto3.client('bedrock-agent-runtime')
s3_client = boto3.client('s3',region_name=os.environ['AWS_REGION'],config=boto3.session.Config(signature_version='s3v4',))

# New Bedrock Runtime client
bedrock_runtime = boto3.client(
    service_name = "bedrock-runtime",
    region_name = "us-east-1"
)

# Streamlit CSS
custom_css = """
    <style>
        .text-with-bg {
        color: white;
            background-color: #1c2e4a; /* Change this to your desired background color */
            padding: 10px;
            border-radius: 5px;
        }
    </style>
"""

# Streamlit App Layout
st.title('Amazon Bedrock AOH Agent')
st.subheader('Powered by coffee and Amazon Bedrock')
st.info("**DISCLAIMER:** This demo uses an Amazon Bedrock foundation model and is not intended to collect any personally identifiable information (PII) from users. Please do not provide any PII when interacting with this demo. The content generated by this demo is for informational purposes only.")
idp_logo = "bedrock_logo.png"
st.sidebar.image(idp_logo, width=300, output_format='PNG')
st.sidebar.markdown(custom_css, unsafe_allow_html=True)
st.sidebar.subheader('**About this Demo**')
st.sidebar.markdown('<p class="text-with-bg">The Bedrock Affidavit of Heirship (AOH) Agent solution uses an Amazon Bedrock Anthropic 2.1 foundation model and LangChain to assist title examiners and human underwriters by extracting work instructions which are then applied to the recently uploaded AOH document. </p>', unsafe_allow_html=True)

# Helper Functions
def document_loader(incoming_document, doc_type):
    # New Textract loader
    s3_loader = AmazonTextractPDFLoader(incoming_document)
    document = s3_loader.load()

    # New document iterator
    if doc_type == "aoh":
        print("AOH Length: " + str(len(document)))
        st.write("AOH Length: ", str(len(document)))
    else:
        print("Instruction Document Length: " + str(len(document)))
        st.write("Instruction Document Length:", str(len(document)))
    fulltext = ""
    for page in document:
        fulltext += page.page_content
        #print(page.page_content)

    return fulltext

def load_instructions(instr_text):
    # Loading instructions and applying to AOH
    template = """

    You are a helpful assistant to a title examiner. From {instr_text}, please provide a bulleted list of the First American requirements as set forth in code ATRQ/T137.

    """
    prompt = PromptTemplate(template=template,input_variables=[""])

    bedrock_llm = Bedrock(
        model_id=model_id,
        client=bedrock_runtime,
        model_kwargs={
                        'max_tokens_to_sample': 8192,
                        'temperature': 0.0,
                        'top_k': 250,
                        'top_p': 0.999}
    )
    llm_chain = LLMChain(prompt=prompt, llm=bedrock_llm)
    instructions = llm_chain.run({"instr_text": instr_text})
    # print("Instructions: " + str(instructions))
    # st.write("Instructions: ", str(instructions))

    return instructions

def run_instructions(instructions, aoh_text):

    # Full compliance automation
    template = """

    For each of the requirements in you can identify in {instructions}, extract the corresponding information from {aoh_text}

    <instruction>
    {instructions}
    </instruction>

    <document>
    {aoh_text}
    <document>

    <final_answer>"""
    prompt = PromptTemplate(template=template, input_variables=["aoh_text", "instructions"])
    bedrock_llm = Bedrock(client=bedrock_runtime, model_id=model_id)
    llm_chain = LLMChain(prompt=prompt, llm=bedrock_llm)
    compliance = llm_chain.run({"aoh_text": aoh_text, "instructions": instructions})
    print("Compliance status: " + compliance)
    st.write("Compliance status: ", compliance)

def extract_details(aoh_text):
    # Extract descriptions from AOH
    output_template = {
        "date_affidavit":{ "type": "string", "description": "Date of Affidavit" },
        "deceased_death_date":{ "type": "string", "description": "Date of death of the decedent" },
        "deceased_death_place":{ "type": "string", "description": "Place of death of the decedent" },
        "deceased_residence":{ "type": "string", "description": "Decedent's place of residence at time of death" },
        "deceased_marital":{ "type": "string", "description": "Decedent's complete marital history" },
        "children_all":{ "type": "string", "description": "All children born to, adopted by, or raised in the home of the decedent and whether or not living" },
    }

    template = """

    You are a helpful assistant. Please extract the following details from the document and format the output as JSON using the keys. Put dates in MM/DD/YYYY format.

    <details>
    {details}
    </details>

    <keys>
    {keys}
    </keys>

    <document>
    {aoh_text}
    <document>

    <final_answer>"""

    details = "\n".join([f"{key}: {value['description']}\n" for key, value in output_template.items()])
    keys = "\n".join([f"{key}" for key, value in output_template.items()])

    print("AOH Field Descriptions: " + details)
    st.write("AOH Field Descriptions: ", details)

    # Extract details from AOH
    prompt = PromptTemplate(template=template, input_variables=["details", "keys", "aoh_text"])
    print(prompt)
    bedrock_llm = Bedrock(
        model_id=model_id,
        client=bedrock_runtime,
        model_kwargs={
                        'max_tokens_to_sample': 4096,
                        'temperature': 0.0,
                        'top_k': 250,
                        'top_p': 0.999}
    )
    llm_chain = LLMChain(prompt=prompt, llm=bedrock_llm)
    output = llm_chain.run({"aoh_text": aoh_text, "details": details, "keys": keys})

    print("AOH Field Details: " + output)
    st.write("AOH Field Details: " + output)

def determine_compliance(aoh_text):
    # Answering questions
    question_template = """

    You are a helpful assistant. Please answer the following questions.
    1. Does the {aoh_text} include a statement that there are no unpaid debts of the estate, including estate taxes.  
    2. Does the {aoh_text} include a statement that there has not been any administration or probate opened with respect to the decedent's estate and none is anticipated or necessary.  
    3. Is the {aoh_text} sworn and contains a proper jurat (not an acknowledgement).

    """
    prompt = PromptTemplate(template=question_template,input_variables=[""])

    bedrock_llm = Bedrock(client=bedrock_runtime, model_id=model_id)
    llm_chain = LLMChain(prompt=prompt, llm=bedrock_llm)
    output = llm_chain.run({"aoh_text": aoh_text})
    print("Does the AOH contain the necessary elements?\n" + str(output))
    st.write("Does the AOH contain the necessary elements?\n", str(output))

    # Answering questions
    question_template = """

    You are a helpful assistant. Please answer the following question. Answer Yes or NO and provide reference in the document.
    Does the {aoh_text} include signatures of at least two disinterested parties having personal knowledge of the family history of the decedent and having personally known the decedent for at least ten years.
    """
    prompt = PromptTemplate(template=question_template,input_variables=[""])

    bedrock_llm = Bedrock(client=bedrock_runtime, model_id=model_id)
    llm_chain = LLMChain(prompt=prompt, llm=bedrock_llm)
    output = llm_chain.run({"aoh_text": aoh_text})
    print("Does the AOH contain the necessary signature?\n" + str(output))
    st.write("Does the AOH contain the necessary signature?\n", str(output))

def document_summary(aoh_text):
    # Document summarization
    summary_template = """

    Given a full document, give me a concise summary.

    <document>{aoh_text}</document>
    <summary>"""

    prompt = PromptTemplate(template=summary_template, input_variables=["aoh_text"])

    bedrock_llm = Bedrock(client=bedrock_runtime, model_id=model_id)
    num_tokens = bedrock_llm.get_num_tokens(aoh_text)
    print ("Prompt token size: " + str(num_tokens))
    llm_chain = LLMChain(prompt=prompt, llm=bedrock_llm)
    summary = llm_chain.run(aoh_text)

    return summary

def show_pdf(uploaded_file):
    if uploaded_file is not None:
        file_contents = uploaded_file.getvalue()

        # Convert the file content to base64
        base64_pdf = base64.b64encode(file_contents).decode('utf-8')
        
        # Display the PDF
        pdf_display = f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="500" height="500" type="application/pdf"></iframe>'
        st.markdown(pdf_display, unsafe_allow_html=True)

def s3_upload_object(file_content, bucket_name, s3_file_name):
    print("Uploading document to Amazon S3")

    try:
        # Wrap the bytes content in an in-memory file-like object
        file_obj = io.BytesIO(file_content)

        s3_client.upload_fileobj(file_obj, bucket_name, s3_file_name)

        aoh_document = "s3://" + bucket_name + "/" + s3_file_name
        st.success(f"File uploaded successfully to S3 bucket '{bucket_name}' as '{s3_file_name}'")
    except Exception as e:
        st.error(f"Error uploading file to S3: {e}")
    finally:
        file_obj.close()  # Close the file-like object after upload

    return "Agent response example"

def main():
    # Main Execution Block
    if "invoke_agent_clicked" not in st.session_state:
        st.session_state["invoke_agent_clicked"] = False

    # Initialize flag to track whether a document has been uploaded
    document_uploaded = False

    # --- Knowledge Base Update ---
    st.subheader("AOH - File Upload")
    uploaded_file = st.file_uploader("Upload Document", type=["csv", "doc", "docx", "htm", "html", "md", "pdf", "txt", "xls", "xlsx"])

    if uploaded_file is not None:
        document_uploaded = True  # Set flag to True if document is uploaded

        with st.expander("Uploaded File 📁"):
            show_pdf(uploaded_file)

            # Display the contents of the file (for text-based formats like txt, pdf, docx)
            if uploaded_file.type == "text/plain":
                text = uploaded_file.read()
                st.write("Content:")
                st.write(text.decode("utf-8"))  # Decode bytes to string for display

            if st.session_state["invoke_agent_clicked"] == False:
                file_contents = uploaded_file.getvalue()
                s3_upload_object(file_contents, knowledge_base_s3_bucket, uploaded_file.name)

    # Button to invoke the agent - Only selectable if a document has been uploaded
    if document_uploaded:
        # --- Agent Q&A ---
        st.subheader('AOH - Agent Analysis')

        if st.button("Run Compliance Check"):
            st.session_state["invoke_agent_clicked"] = True
            
            # Instructions
            instr_text = document_loader(instruction_s3, "instructions")
            instructions = load_instructions(instr_text)
            instr_summary = document_summary(instr_text)

            print("Document Summary: " + instr_summary.replace("</summary>","").strip())
            st.write("Document Summary: ", instr_summary.replace("</summary>","").strip())

            # AOH
            aoh_text = document_loader(aoh_document, "aoh")
            run_instructions(instructions, aoh_text)
            extract_details(aoh_text)
            determine_compliance(aoh_text)
            aoh_summary = document_summary(aoh_text)

            # Refresh the Streamlit session
            # st.experimental_rerun()
    else:
        # If no file uploaded, display a placeholder
        st.write("No document uploaded.")

# Call the main function to run the app
if __name__ == "__main__":
    main()