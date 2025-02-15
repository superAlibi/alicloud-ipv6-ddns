# Aliyun IPv6 DDNS Client

A Python-based DDNS client for updating Aliyun DNS records with IPv6 addresses.

## Project Structure

```
.
├── README.md
├── README.en.md
├── requirements.txt
├── config.toml
└── src/
    └── main.py
```

## Requirements

- Python 3.8+

## Installation

1. Clone the repository
2. Install dependencies:
```bash
pip install -r requirements.txt
```

## Configuration

Create a `config.toml` file with the following structure:

```toml
# Aliyun Access Key
[credentials]
access_key_id = "your_access_key_id"
access_key_secret = "your_access_key_secret"

# Domain Settings
# Format: interface_name = "domain_name"
[domain_map]
enp2s0 = "your domain_name"
enp4s0 = "your domain_name"

# DNS Record Settings
[dns]
# List of record prefixes
record_prefixes = ["@", "*", "www", "nginx-hello"]
record_type = "AAAA"
```

## Usage

Run the client with default settings:
```bash
python src/main.py
```

Run with a specific configuration file:
```bash
python src/main.py --config custom_config.toml
```

The client will check for IPv6 address changes every 5 minutes and update DNS records accordingly.

## Features

- Automatic IPv6 address detection
- Support for multiple network interfaces
- Multiple DNS record prefixes
- Configurable update interval
- Detailed logging
