import boto3
import time
from datetime import datetime

BUCKET = "elasticbeanstalk-ap-southeast-2-833563724651"
APP_NAME = "sa-algal-bloom-api"
ENV_NAME = "sa-algal-bloom-api-env"
ZIP_PATH = "deploy_aws.zip"

timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
version_label = f"algal-bloom-refresh-{timestamp}"
s3_key = f"deploy_aws_{timestamp}.zip"

print(f"1. Uploading {ZIP_PATH} to S3 bucket {BUCKET} as {s3_key}...")
s3 = boto3.client('s3')
s3.upload_file(ZIP_PATH, BUCKET, s3_key)
print("   Upload complete.")

print(f"2. Creating EB Application Version: {version_label}...")
eb = boto3.client('elasticbeanstalk')
eb.create_application_version(
    ApplicationName=APP_NAME,
    VersionLabel=version_label,
    SourceBundle={
        'S3Bucket': BUCKET,
        'S3Key': s3_key
    },
    AutoCreateApplication=False
)
print("   Application version created.")

print(f"3. Deploying version {version_label} to environment {ENV_NAME}...")
eb.update_environment(
    EnvironmentName=ENV_NAME,
    VersionLabel=version_label
)
print("   Deploy command sent. Monitoring deployment status...")

# Monitor deployment progress
while True:
    envs = eb.describe_environments(EnvironmentNames=[ENV_NAME])['Environments']
    if not envs:
        print("Error: Environment not found.")
        break
    env = envs[0]
    status = env['Status']
    health = env['Health']
    health_status = env.get('HealthStatus', 'unknown')
    
    print(f"   [{datetime.now().strftime('%H:%M:%S')}] Status: {status} | Health: {health} ({health_status})")
    
    if status == 'Ready':
        print(f"\nSUCCESS: Deployment complete! Environment CNAME: {env['CNAME']}")
        break
        
    time.sleep(10)
