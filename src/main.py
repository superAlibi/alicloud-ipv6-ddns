#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import logging
import os
import time
import argparse
from datetime import datetime
from typing import Dict, List, Optional

import netifaces
from dotenv import load_dotenv
from aliyunsdkcore.client import AcsClient
from aliyunsdkcore.acs_exception.exceptions import ClientException
from aliyunsdkcore.acs_exception.exceptions import ServerException
from aliyunsdkalidns.request.v20150109.DescribeDomainRecordsRequest import DescribeDomainRecordsRequest
from aliyunsdkalidns.request.v20150109.UpdateDomainRecordRequest import UpdateDomainRecordRequest
from aliyunsdkalidns.request.v20150109.AddDomainRecordRequest import AddDomainRecordRequest

def setup_logger():
    """初始化日志记录器"""
    # 确定日志目录
    if os.getenv('RUNNING_IN_SYSTEMD') == 'true':
        log_dir = '/var/log/alicloud-ddns'
    else:
        log_dir = 'logs'
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)

    # 生成日志文件名，使用当前日期
    log_file = os.path.join(log_dir, f'ddns_{datetime.now().strftime("%Y%m%d")}.log')
    
    # 创建日志记录器
    logger = logging.getLogger('DDNSLogger')
    logger.setLevel(logging.INFO)

    # 创建文件处理器
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.INFO)

    # 创建控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    # 设置日志格式
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    # 添加处理器
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger

class AliyunDDNS:
    def __init__(self, access_key_id: str, access_key_secret: str, interface_domain_map: Dict[str, str],
                 rr_list: List[str], record_type: str):
        self.client = AcsClient(access_key_id, access_key_secret, 'cn-hangzhou')
        self.interface_domain_map = interface_domain_map
        self.rr_list = rr_list
        self.type = record_type

    def get_interface_ipv6(self, interface: str) -> Optional[str]:
        """获取指定接口的公网IPv6地址"""
        try:
            if interface not in netifaces.interfaces():
                self.logger.warning(f'接口 {interface} 不存在')
                return None

            addrs = netifaces.ifaddresses(interface)
            if netifaces.AF_INET6 not in addrs:
                self.logger.warning(f'接口 {interface} 没有IPv6地址')
                return None

            ipv6_addrs = []
            for addr in addrs[netifaces.AF_INET6]:
                ip = addr['addr'].split('%')[0]  # 去除接口ID

                # 过滤非公网IPv6地址
                if any([
                    ip.startswith('fe80:'),
                    ip.startswith('fc00:'),
                    ip.startswith('fd00:'),
                    ip == '::1',
                    ip.startswith('2002:'),
                    ip.startswith('3ffe:'),
                    ':' not in ip
                ]):
                    continue

                # 如果是公网IPv6地址
                if ip.startswith('2') or ip.startswith('3'):
                    ipv6_addrs.append(ip)

            if ipv6_addrs:
                # 按字符串长度排序，优先选择非临时地址
                ipv6_addrs.sort(key=len)
                return ipv6_addrs[0]
            else:
                self.logger.warning(f'接口 {interface} 没有公网IPv6地址')
                return None

        except Exception as e:
            self.logger.error(f'获取接口 {interface} 的IPv6地址失败: {str(e)}')
            return None

    def get_domain_records(self, domain: str, rr: str) -> Optional[Dict]:
        """获取域名解析记录"""
        request = DescribeDomainRecordsRequest()
        request.set_accept_format('json')
        request.set_DomainName(domain)
        request.set_RRKeyWord(rr)
        request.set_Type(self.type)

        try:
            response = self.client.do_action_with_exception(request)
            records = json.loads(response)['DomainRecords']['Record']
            return records[0] if records else None
        except Exception as e:
            self.logger.error(f'获取域名解析记录失败 ({domain}:{rr}): {str(e)}')
            return None

    def add_domain_record(self, ip: str, domain: str, rr: str) -> bool:
        """创建新的域名解析记录"""
        request = AddDomainRecordRequest()
        request.set_accept_format('json')
        request.set_DomainName(domain)
        request.set_RR(rr)
        request.set_Type(self.type)
        request.set_Value(ip)

        try:
            self.client.do_action_with_exception(request)
            self.logger.info(f'成功创建DNS记录: {rr}.{domain} -> {ip}')
            return True
        except Exception as e:
            self.logger.error(f'创建DNS记录失败 ({rr}.{domain}): {str(e)}')
            return False

    def update_domain_record(self, record_id: str, current_ip: str, domain: str, rr: str) -> bool:
        """更新域名解析记录"""
        request = UpdateDomainRecordRequest()
        request.set_accept_format('json')
        request.set_RecordId(record_id)
        request.set_RR(rr)
        request.set_Type(self.type)
        request.set_Value(current_ip)

        try:
            self.client.do_action_with_exception(request)
            self.logger.info(f'成功更新DNS记录: {rr}.{domain} -> {current_ip}')
            return True
        except Exception as e:
            self.logger.error(f'更新DNS记录失败 ({rr}.{domain}): {str(e)}')
            return False

    def sync(self) -> None:
        """同步DNS记录"""
        # 遍历每个接口和对应的域名
        for interface, domain in self.interface_domain_map.items():
            current_ip = self.get_interface_ipv6(interface)
            if not current_ip:
                continue

            # 更新该域名的所有主机记录
            for rr in self.rr_list:
                record = self.get_domain_records(domain, rr)
                if not record:
                    self.logger.info(f'未找到域名解析记录,准备创建: {rr}.{domain}')
                    self.add_domain_record(current_ip, domain, rr)
                    continue

                if record['Value'] != current_ip:
                    self.update_domain_record(record['RecordId'], current_ip, domain, rr)
                else:
                    self.logger.info(f'DNS记录已是最新: {rr}.{domain} -> {current_ip} ({interface})')

def get_mode() -> str:
    """获取运行模式"""
    parser = argparse.ArgumentParser(description='阿里云DDNS客户端')
    parser.add_argument('--mode', type=str,
                        help='运行模式 (默认: production)')
    args = parser.parse_args()
    return args.mode

def load_env_files(mode: str,logger: logging.Logger) -> None:
    """按照优先级顺序加载环境变量文件"""
    # 先加载基础配置
    if os.path.exists('.env'):
        load_dotenv('.env')
        logger.info('已加载: .env')
    
    # 加载模式特定的配置
    mode_env = f'.env.{mode}'
    if os.path.exists(mode_env):
        load_dotenv(mode_env, override=True)
        logger.info(f'已加载: {mode_env}')
    
    # 加载本地配置（最高优先级）
    local_env = f'.env.{mode}.local'
    if os.path.exists(local_env):
        load_dotenv(local_env, override=True)
        logger.info(f'已加载: {local_env}')
    elif os.path.exists('.env.local'):
        load_dotenv('.env.local', override=True)
        logger.info('已加载: .env.local')

def load_config(logger: logging.Logger) -> tuple:
    """从环境变量加载配置"""
    try:
        # 按照优先级加载环境变量文件
        mode = get_mode()
        load_env_files(mode,logger)
        
        # 读取必需的凭证
        access_key_id = os.getenv('ALIYUN_ACCESS_KEY_ID')
        access_key_secret = os.getenv('ALIYUN_ACCESS_KEY_SECRET')
        
        if not all([access_key_id, access_key_secret]):
            raise ValueError('未设置阿里云访问凭证')
            
        # 构建接口和域名的映射关系
        interface_domain_map = {}
        for key, value in os.environ.items():
            if key.startswith('DOMAIN_MAP_'):
                interface = key.replace('DOMAIN_MAP_', '').lower()
                interface_domain_map[interface] = value
        
        if not interface_domain_map:
            raise ValueError('未设置域名映射关系')
            
        # 读取DNS记录设置
        record_prefixes = os.getenv('DNS_RECORD_PREFIXES', '@,*,www').split(',')
        record_type = os.getenv('DNS_RECORD_TYPE', 'AAAA')
        
        return access_key_id, access_key_secret, interface_domain_map, record_prefixes, record_type
    except Exception as e:
        logger.error(f'加载配置失败: {str(e)}')
        return None, None, None, None, None

def main():
    # 初始化日志记录器
    logger = setup_logger()
    
    # 加载配置
    access_key_id, access_key_secret, interface_domain_map, record_prefixes, record_type = load_config(logger)
    
    if not all([access_key_id, access_key_secret, interface_domain_map, record_prefixes, record_type]):
        logger.error('配置加载失败')
        return

    # 创建DDNS客户端
    ddns = AliyunDDNS(access_key_id, access_key_secret, interface_domain_map, record_prefixes, record_type)
    ddns.logger = logger
    
    update_interval = 300  # 5分钟更新一次
    logger.info(f'DDNS服务已启动，每{update_interval}秒检查一次IP变化...')
    
    try:
        while True:
            ddns.sync()
            time.sleep(update_interval)
    except KeyboardInterrupt:
        logger.info('\nDDNS服务已停止')

if __name__ == '__main__':
    main()
