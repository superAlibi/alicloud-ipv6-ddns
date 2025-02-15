# 阿里云 IPv6 DDNS 客户端

[English](README.en.md) | 简体中文

一个基于 Python 的 DDNS 客户端，用于更新阿里云 DNS 记录的 IPv6 地址。

## 项目结构

```
.
├── README.md
├── README.en.md
├── requirements.txt
├── config.toml
└── src/
    └── main.py
```

## 环境要求

- Python 3.8+

## 安装

1. 克隆仓库
2. 安装依赖：
```bash
pip install -r requirements.txt
```

## 配置

创建 `config.toml` 文件，结构如下：

```toml
# 阿里云访问凭证
[credentials]
access_key_id = "your_access_key_id"
access_key_secret = "your_access_key_secret"

# 域名设置
# 格式：网卡名称 = "域名"
[domain_map]
enp2s0 = "your domain_name"
enp4s0 = "your domain_name"

# DNS记录设置
[dns]
# 记录前缀列表
record_prefixes = ["@", "*", "www", "nginx-hello"]
record_type = "AAAA"
```

## 使用方法

使用默认配置运行：
```bash
python src/main.py
```

指定配置文件运行：
```bash
python src/main.py --config custom_config.toml
```

客户端会每5分钟检查一次IPv6地址变化，并相应更新DNS记录。

## 功能特性

- 自动检测IPv6地址
- 支持多个网络接口
- 支持多个DNS记录前缀
- 可配置的更新间隔
- 详细的日志记录
