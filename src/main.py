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
import toml
from aliyunsdkcore.client import AcsClient
from aliyunsdkalidns.request.v20150109.DescribeDomainRecordsRequest import DescribeDomainRecordsRequest
from aliyunsdkalidns.request.v20150109.UpdateDomainRecordRequest import UpdateDomainRecordRequest
from aliyunsdkalidns.request.v20150109.AddDomainRecordRequest import AddDomainRecordRequest

def setup_logger(running_in_systemd):
    """初始化日志记录器"""
    # 统一日志目录为项目目录下的 logs
    log_dir = os.path.join(os.path.dirname(__file__), '../logs')
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

    # 设置日志格式
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)

    # 添加处理器
    logger.addHandler(file_handler)

    # 如果不是在systemd中运行，则添加控制台处理器
    if not running_in_systemd:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger

class AliyunDDNS:
    def __init__(self, access_key_id: str, access_key_secret: str, domains: List[Dict[str, str]]):
        self.client = AcsClient(access_key_id, access_key_secret, 'cn-hangzhou')
        self.domains = domains
        self.logger = logging.getLogger('DDNSLogger')

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

    def get_domain_records(self, domain: str, rr: str,type:str) -> Optional[Dict]:
        """获取域名解析记录"""
        request = DescribeDomainRecordsRequest()
        request.set_accept_format('json')
        request.set_DomainName(domain)
        request.set_RRKeyWord(rr)
        request.set_Type(type)

        try:
            response = self.client.do_action_with_exception(request)
            records = json.loads(response)['DomainRecords']['Record']
            return records[0] if records else None
        except Exception as e:
            self.logger.error(f'获取域名解析记录失败 ({domain}:{rr}): {str(e)}')
            return None

    def add_domain_record(self, ip: str, domain: str, rr: str,type:str) -> bool:
        """创建新的域名解析记录"""
        request = AddDomainRecordRequest()
        request.set_accept_format('json')
        request.set_DomainName(domain)
        request.set_RR(rr)
        request.set_Type(type)
        request.set_Value(ip)

        try:
            self.client.do_action_with_exception(request)
            self.logger.info(f'成功创建DNS记录: {rr}.{domain} -> {ip}')
            return True
        except Exception as e:
            self.logger.error(f'创建DNS记录失败 ({rr}.{domain}): {str(e)}')
            return False

    def update_domain_record(self, record_id: str, current_ip: str, domain: str, rr: str,type:str) -> bool:
        """更新域名解析记录"""
        request = UpdateDomainRecordRequest()
        request.set_accept_format('json')
        request.set_RecordId(record_id)
        request.set_RR(rr)
        request.set_Type(type)
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
        # 遍历每个接口和对应的域名列表
        for domainInfo in self.domains:
            current_ip = self.get_interface_ipv6(domainInfo['bind_interface'])
            if not current_ip:
                continue

            # 遍历所有的子域名前缀
            for subdomain in domainInfo['subdomain']:
                record = self.get_domain_records(domainInfo['domain_name'], subdomain,domainInfo['type'])
                if not record:
                    self.logger.info(f'未找到域名解析记录,准备创建: {subdomain}.{domainInfo['domain_name']}')
                    self.add_domain_record(current_ip, domainInfo['domain_name'], subdomain,domainInfo['type'])
                    continue

                if record['Value'] != current_ip:
                    self.update_domain_record(record['RecordId'], current_ip, domainInfo['domain_name'], subdomain,domainInfo['type'])
                else:
                    self.logger.info(f'DNS记录已是最新: {subdomain}.{domainInfo['domain_name']} -> {current_ip}')



def load_config(logger: logging.Logger,args:argparse.Namespace) -> tuple:
    """从TOML文件加载配置"""
    try:
        # 获取配置文件路径
        config_file = args.config
        local_config_file = config_file.replace('.toml', '.local.toml')
        
        # 检查配置文件是否存在
        if not os.path.exists(config_file):
            raise ValueError(f'配置文件不存在: {config_file}')
        
        # 加载TOML配置
        config = toml.load(config_file)
        logger.info(f'已加载配置文件: {config_file}')
        
        # 如果存在本地配置文件，加载并覆盖配置
        if os.path.exists(local_config_file):
            local_config = toml.load(local_config_file)
            logger.info(f'已加载本地配置文件: {local_config_file}')
            # 使用本地配置覆盖默认配置
            config.update(local_config)
        
        # 读取必需的凭证
        credentials = config.get('credentials', {})
        access_key_id = credentials.get('access_key_id')
        access_key_secret = credentials.get('access_key_secret')
        
        if not all([access_key_id, access_key_secret]):
            raise ValueError('未设置阿里云访问凭证')
        
        # 获取域名映射关系
        domains = config.get('domains', [])
        if not domains:
            raise ValueError('未设置域名映射关系')
        return access_key_id, access_key_secret, domains # 将集合转换回列表
    except Exception as e:
        logger.error(f'加载配置失败: {str(e)}')
        return None, None, None

def main():
    parser = argparse.ArgumentParser(description='阿里云DDNS客户端')
    parser.add_argument('--running-in-systemd', action='store_true', help='Indicate if running in systemd environment')
    parser.add_argument('--config', type=str, default='config.toml',
                        help='配置文件路径 (默认: config.toml)')
    args = parser.parse_args()
   
    # 初始化日志记录器
    logger = setup_logger(args.running_in_systemd)
    
    # 加载配置
    access_key_id, access_key_secret, domains = load_config(logger,args)
    if not all([access_key_id, access_key_secret, domains]):
        logger.error('配置加载失败')
        return
    
    # 创建DDNS客户端
    ddns = AliyunDDNS(access_key_id, access_key_secret, domains)
    ddns.logger = logger
    
    update_interval = 300  # 5分钟更新一次
    logger.info(f'DDNS服务已启动，每{update_interval}秒检查一次IP变化...')
    
    try:
        while True:
            ddns.sync()
            time.sleep(update_interval)
    except KeyboardInterrupt:
        logger.info('DDNS服务已停止')

if __name__ == '__main__':
    main()
