"""
MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

Author: Shailendra Dharmistan, Zcaler Inc.
"""

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import boto3
import gevent
import logging
import requests
import schedule
from azure.identity import DefaultAzureCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.network import NetworkManagementClient
from gevent import monkey


# Patch all to make standard library cooperative
monkey.patch_all()

# Get the logger that was created in __main__.py
logger = logging.getLogger('__main__')

CONCURRENCY_MODEL = 'thread'
# Load settings from the JSON file
def load_settings(settings_file='settings.json'):
    # Load settings from the settings file
    # handle the case where the settings file is not found
    if not os.path.exists('./settings.json'):
        logger.critical("settings.json must be present in your project folder. Please refer to the README for more information.")
        return {}
    with open('./settings.json') as f:
        return json.load(f)

# Load settings
settings = load_settings()

# Configuration for AWS and Azure
aws_region = settings['aws_region']
asg_name = settings['asg_name']
subscription_id = settings['subscription_id']
resource_group = settings['resource_group']
vmss_name = settings['vmss_name']
ssh_key_path = settings['ssh_key_path']
ssh_username = settings['ssh_username']
remote_paths = settings['remote_paths']
interval = settings.get('interval', 60)  # Default to 60 seconds if not specified
base_local_dir = settings.get('base_local_dir', './')  # Default to current directory if not specified
sudo_path = settings.get('sudo_path', '/usr/local/bin/sudo')  # Default to /usr/local/bin/sudo if not specified
# device index for network interface to get the private IP address. Must be an integer.
device_index = settings.get('device_index', 1)

# Function to get the interval from settings
def get_interval():
    return interval

# Function to get AWS metadata token for IMDSv2
def get_aws_metadata_token():
    try:
        response = requests.put('http://169.254.169.254/latest/api/token', headers={'X-aws-ec2-metadata-token-ttl-seconds': '21600'}, timeout=1)
        if response.status_code == 200:
            return response.text
        else:
            logger.info(f"Failed to get AWS metadata token: {response.status_code} {response.text}")
    except requests.RequestException as e:
        logger.info(f"Exception occurred while getting AWS metadata token: {e}")
    return None

# Detect cloud environment
def detect_cloud_environment():
    # Check for AWS environment by querying the metadata service with IMDSv2
    token = get_aws_metadata_token()
    if token:
        try:
            # Check for AWS environment by querying the metadata service
            response = requests.get('http://169.254.169.254/latest/meta-data/', headers={'X-aws-ec2-metadata-token': token}, timeout=1)
            if response.status_code == 200:
                logger.info("Detected AWS environment")
                return 'aws'
            else:
                # log the error with response body and status code
                logger.info(f"Failed to query AWS metadata service: {response.status_code} - {response.text}")
        except requests.RequestException as e:
            logger.info(f"Failed to query AWS metadata service: {e}")

    try:
        # Check for Azure environment by querying the metadata service
        headers = {'Metadata': 'true'}
        response = requests.get('http://169.254.169.254/metadata/instance?api-version=2021-02-01', headers=headers, timeout=1)
        if response.status_code == 200:
            logger.info("Detected Azure environment")
            return 'azure'
        else:
            # log the error with response body and status code
            logger.info(f"Failed to query Azure metadata service: {response.status_code} - {response.text}")
    except requests.RequestException as e:
        logger.info(f"Failed to query Azure metadata service: {e}")

    logger.error("Unsupported cloud environment")
    return None

# Function to get and create VM list from the settings.json file
def get_static_vm_list():
    vm_list = []
    if settings.get('cc_vms'):
        cc_vms = settings['cc_vms']
        for vm in cc_vms:
            vm_list.append({
                'hostname': vm,
                'username': ssh_username,
                'key_filename': ssh_key_path,
                'remote_paths': remote_paths
            })
    return vm_list

# Function to get instances from AWS ASG
def get_asg_instances():
    client = boto3.client('autoscaling', region_name=aws_region)
    ec2 = boto3.client('ec2', region_name=aws_region)

    response = client.describe_auto_scaling_groups(AutoScalingGroupNames=[asg_name])
    instance_ids = [instance['InstanceId'] for instance in response['AutoScalingGroups'][0]['Instances'] if instance['LifecycleState'] == 'InService']

    reservations = ec2.describe_instances(InstanceIds=instance_ids)
    instances = []
    for reservation in reservations['Reservations']:
        for instance in reservation['Instances']:
            # get the ip address of the network interface with device index 1
            network_interface = next((interface for interface in instance['NetworkInterfaces'] if interface['Attachment']['DeviceIndex'] == device_index), None)
            host_ip = network_interface['PrivateIpAddress'] if network_interface else None
            if host_ip:
                instances.append({
                    'hostname': host_ip,
                    'username': ssh_username,
                    'key_filename': ssh_key_path,
                    'remote_paths': remote_paths  # Use remote paths from settings
                })
    return instances

# Function to get instances from Azure VMSS
def get_vmss_instances():
    credential = DefaultAzureCredential()
    compute_client = ComputeManagementClient(credential, subscription_id)

    instances = compute_client.virtual_machine_scale_set_vms.list(resource_group, vmss_name)
    vm_list = []

    for instance in instances:
        # Get instance details
        network_profile = instance.network_profile.network_interfaces[device_index]
        nic_id = network_profile.id
        nic_name = nic_id.split('/')[-1]
        
        # Get NIC details
        network_client = NetworkManagementClient(credential, subscription_id)
        nic = network_client.network_interfaces.get(resource_group, nic_name)
        
        # Get private IP
        private_ip = None
        for ip_config in nic.ip_configurations:
            if ip_config.private_ip_address:
                private_ip = ip_config.private_ip_address.id
                break
        
        if private_ip:
            private_ip = network_client.private_ip_addresses.get(resource_group, private_ip.split('/')[-1]).ip_address

        if private_ip:
            vm_list.append({
                'hostname': private_ip,
                'username': ssh_username,
                'key_filename': ssh_key_path,
                'remote_paths': remote_paths  # Use remote paths from settings
            })
    
    return vm_list

# Function to connect to a VM and copy files using rsync
def copy_files_from_vm(vm_info, local_dir):
    try:
        for remote_path in vm_info['remote_paths']:
            # Construct the local path by appending the remote path to the base local directory
            local_path = os.path.join(local_dir, vm_info['hostname'], remote_path.lstrip('/'))
            os.makedirs(local_path, exist_ok=True)
            
            # Construct the rsync command with the specified sudo path
            rsync_command = (
                f"rsync -az -e 'ssh -o StrictHostKeyChecking=no -i {vm_info['key_filename']}' "
                f"--rsync-path='{sudo_path} rsync' {vm_info['username']}@{vm_info['hostname']}:{remote_path}/ {local_path}/"
            )
            logger.info(f"Running command: {rsync_command}")
            
            # Execute the rsync command locally
            os.system(rsync_command)
        
        logger.info(f"Successfully copied files from {vm_info['hostname']} to {local_path}")
    except Exception as e:
        logger.error(f"Failed to copy files from {vm_info['hostname']}: {e}")

# Function to get the VM list
def get_vm_list():
    if settings.get('cc_vms'):
        return get_static_vm_list()
    cloud_env = detect_cloud_environment()
    if cloud_env == 'aws':
        return get_asg_instances()
    elif cloud_env == 'azure':
        return get_vmss_instances()
    else:
        print("Unsupported cloud environment")
        return []

# Function to run the copy process for all VMs concurrently
def run_copy_process():
    vm_list = get_vm_list()
    if not vm_list:
        logger.info("No instances found")
        return
    if CONCURRENCY_MODEL == 'thread':
        with ThreadPoolExecutor() as executor:
            futures = [executor.submit(copy_files_from_vm, vm_info, base_local_dir) for vm_info in vm_list]
            for future in as_completed(futures):
                future.result()
    elif CONCURRENCY_MODEL == 'gevent':
        jobs = [gevent.spawn(copy_files_from_vm, vm_info, base_local_dir) for vm_info in vm_list]
        gevent.joinall(jobs)
    else:
        # run sequentially
        for vm_info in vm_list:
            copy_files_from_vm(vm_info, base_local_dir)

# Detect cloud environment once at startup
cloud_env = detect_cloud_environment()
if cloud_env is None:
    logger.critical("Failed to detect cloud environment. Exiting.")
    exit(1)

# Schedule the copy process to run periodically
schedule.every(interval).seconds.do(run_copy_process)

# Main loop to keep the script running and executing the scheduled tasks
if __name__ == "__main__":
    while True:
        schedule.run_pending()
        time.sleep(1)
