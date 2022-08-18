import os
from pathlib import Path
from dotenv import load_dotenv

import smtplib
from http import HTTPStatus
from smtplib import SMTPAuthenticationError, SMTPRecipientsRefused

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import boto3
from botocore.exceptions import ClientError

from flask import Flask, request, Response
from jinja2 import Template
import json

dot_local = Path('./.env-local')
load_dotenv(dotenv_path=dot_local)

SMTP_USER = os.getenv('SMTP_USER')
SMTP_PASS = os.getenv('SMTP_PASS')
SMTP_SENDER = os.getenv('SMTP_SENDER')

S3_BUCKET_NAME = 'py-notifier'
app = Flask(__name__)


class S3Error(Exception):
    pass


def _send_message(messsage):
    smtp = smtplib.SMTP_SSL('email-smtp.us-east-2.amazonaws.com', 465)
    try:
        smtp.login(
            user=SMTP_USER
            password=SMTP_PASS)
    except SMTPAuthenticationError:
        return Response('Authentication failed', status=HTTPStatus.UNAUTHORIZED)
    try:
        smtp.sendmail(message['From'], message['To'], message.as_string())
    except SMTPRecipientsRefused as e:
        return Response(f'Recipient refused {e}', status=HTTPStatus.INTERNAL_SERVER_ERROR)
    finally:
        smtp.quit()

    return Response('Email Sent', status=HTTPStatus.OK)


def _prepare_template(template_name, context_data):
    s3_client = boto3.client('s3')

    try:
        file = s3_client.get_object(Bucket=S3_BUCKET_NAME, Key=template_name)
    except ClientError as ex:
        error = ex.response.get('Error')
        error_code = error.get('Code')

        if error_code == 'NoSuchBucket':
            raise S3Error(
                f'The bucket {S3_BUCKET_NAME} does not exist') from ex
        elif error_code == 'NoSuchKey':
            raise S3Error(
                (f'Could not find the file "{template_name}"' f'in the S3 bucket {S3_BUCKET_NAME}')) from ex
        else:
            raise ex

    content = file['Body'].read().decode('utf-8')
    template = Template(content)

    return template.render(context_data)


@app.route("/notify/order-received", methods=['POST'])
def notify_order_received():
    data = json.loads(request.data)
    order_items = data.get('items')

    customer = data.get('order_customer')
    customer_email = customer.get('email')
    customer_name = customer.get('name')

    order_id = data.get('id')
    total_purchased = data.get('total')

    message = MIMEMultipart('alternative')

    context = {
        'order_items': order_items,
        'customer_name': customer_name,
        'order_id': order_id,
        'total_purchased': total_purchased
    }

    try:
        email_content = _prepare_template(
            'order_received_template.html', context
        )
    except S3Error as ex:
        return Response(str(ex), status=HTTPStatus.INTERNAL_SERVER_ERROR)
    message.attach(MIMEText(email_content, 'html'))

    message['Subject'] = f'ORDER: #{order_id} - Thank you!'
    message['From'] = SMTP_SENDER
    message['To'] = customer_email

    return _send_message(message)


@app.route("/notify/order-shipped/", methods=['POST'])
def notify_order_shipped():
    data = json.loads(request.data)
    customer = data.get('order_customer')
    customer_email = customer.get('email')
    customer_name = customer.get('name')
    order_id = data.get('id')
    message = MIMEMultipart('alternative')
    try:
        email_content = _prepare_template(
            'order_shipped_template.html',
            {'customer_name': customer_name}
        )
    except S3Error as ex:
        return Response(ex,
                        status=HTTPStatus.INTERNAL_SERVER_ERROR)
    message.attach(MIMEText(email_content, 'html'))
    message['Subject'] = f'Order ID #{order_id} has been shipped'
    message['From'] = SMTP_SENDER
    message['To'] = customer_email
    return _send_message(message)
