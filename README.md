# Cloud Connector File Sync Script

This script syncs files from VMs in an Auto Scaling Group (ASG) on AWS or Virtual Machine Scale Set (VMSS) on Azure to a local directory on a bastion host. It uses `rsync` over SSH for file transfers and `gevent` for concurrent execution. The script detects the underlying cloud environment and retrieves the list of instances to perform the sync operation.
The retrieved files from the CC VMs will be stored under separate folders with CC VM IP names.

## Features

- Detects if the script is running in an AWS or Azure environment.
- Retrieves instances from an AWS ASG or Azure VMSS.
- Syncs files from remote paths on VMs to a local directory on the host.
- Maintains the directory structure of the remote paths.
- Uses `thread` or `gevent` for concurrent file transfers.
- Runs the sync operation periodically using `schedule`.

## Requirements

- Python 3.x
- The following Python packages (specified in `requirements.txt`):
  - `boto3`
  - `gevent`
  - `paramiko`
  - `requests`
  - `schedule`
  - `azure-identity`
  - `azure-mgmt-compute`
  - `azure-mgmt-network`

## Installation

1. **Create and activate a virtual environment (optional but recommended)**:
   ```sh
   python3 -m venv venv
   source venv/bin/activate
2. **Clone the repository**:
   ```sh
   git clone https://github.com/dshailen/cc-fsync.git
   cd cc-fsync
3. **Install the dependencies**
   ```sh
   pip install -r requirements.txt
4. **Install cc-fsync modules**
   ```sh
   pip install -e .
4. **Creating a settings file (settings.json)**
  ```json
   {
      "aws_region": "your-aws-region",
      "asg_name": "your-asg-name",
      "subscription_id": "your-azure-subscription-id",
      "resource_group": "your-azure-resource-group",
      "vmss_name": "your-vmss-name",
      "ssh_key_path": "/path/to/your/key.pem",
      "ssh_username": "zsroot",
      "interval": 60,
      "remote_paths": [
         "/sc/run",
         "/etc/janus",
         "/etc/nimbus"
      ],
      "base_local_dir": "./",
      "sudo_path": "/usr/local/bin/sudo",
      "cc_vms": [
      ],
      "device_index": 1,
      "logging": {
         "log_level": "DEBUG",
         "log_file": "cc-fsync.log",
         "max_bytes": 10485760,
         "backup_count": 5
      }
   }
```

## Usage
### To run the script, execute the following command:
   ```sh
   python -m cc_fsync --background
```
### When running under AWS, attach and IAM role with the following rules
```json
   {
      "Version": "2012-10-17",
      "Statement": [
         {
               "Sid": "VisualEditor0",
               "Effect": "Allow",
               "Action": [
                  "autoscaling:DescribeLifecycleHookTypes",
                  "autoscaling:DescribeAutoScalingInstances",
                  "ec2:DescribeInstances",
                  "autoscaling:CompleteLifecycleAction",
                  "autoscaling:DescribeAutoScalingGroups",
                  "autoscaling:DescribeLifecycleHooks",
                  "autoscaling:RecordLifecycleActionHeartbeat",
                  "ec2:DescribeInstanceStatus"
               ],
               "Resource": "*"
         }
      ]
   }
```

#### *If using gevent for concurrency, the following patch is required in the python3.9 ssl libs in addition to the regular monkey patching. The default concurrency model is set to thread*
   ```sh
      edit ..site-packages/urllib3/util/ssl_.py
```
and add the following lines
   ```python
      import gevent
      from gevent import monkey
      monkey.patch_all()
```