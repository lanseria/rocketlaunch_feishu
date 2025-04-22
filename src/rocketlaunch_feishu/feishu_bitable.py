import lark_oapi as lark
from rich.console import Console
from lark_oapi.api.bitable.v1 import UpdateAppTableRecordRequest, AppTableRecord, CreateAppTableRecordRequest
from lark_oapi.api.contact.v3 import *
from dotenv import load_dotenv
import os
import json

console = Console()

class FeishuBitableHelper:
    def __init__(self):
        load_dotenv()
        app_id = os.getenv("FEISHU_APP_ID")
        app_secret = os.getenv("FEISHU_APP_SECRET")
        console.print(app_id, app_secret)
        if not app_id or not app_secret:
            raise ValueError("请在.env文件中配置FEISHU_APP_ID和FEISHU_APP_SECRET")
        self.client = lark.Client.builder() \
            .app_id(app_id) \
            .app_secret(app_secret) \
            .log_level(lark.LogLevel.DEBUG) \
            .build()
        # 新增存储app_token和table_id
        self.app_token = os.getenv("BITABLE_APP_TOKEN")
        self.table_id = os.getenv("BITABLE_TABLE_ID")
        self.view_id = os.getenv("BITABLE_VIEW_ID")

    def list_records(self, field_names=None, sort=None, filter=None, page_size=100):
        from lark_oapi.api.bitable.v1 import SearchAppTableRecordRequest, SearchAppTableRecordRequestBody, Sort, FilterInfo, Condition

        request_body_builder = SearchAppTableRecordRequestBody.builder()

        if self.view_id:
            request_body_builder = request_body_builder.view_id(self.view_id)

        if field_names:
            request_body_builder = request_body_builder.field_names(field_names)

        if sort:
            sort_list = []
            for s in sort:
                sort_obj = Sort.builder() \
                    .field_name(s.get("field_name")) \
                    .desc(s.get("desc", False)) \
                    .build()
                sort_list.append(sort_obj)
            request_body_builder = request_body_builder.sort(sort_list)
        # console.log(filter)
        if filter:
            conditions = []
            for f in filter.get("conditions", []):
                condition = Condition.builder() \
                    .field_name(f.get("field_name")) \
                    .operator(f.get("operator")) \
                    .value(f.get("value")) \
                    .build()
                conditions.append(condition)
            
            filter_info = FilterInfo.builder() \
                .conjunction("and") \
                .conditions(conditions) \
                .build()
            request_body_builder = request_body_builder.filter(filter_info)

        request_body = request_body_builder.automatic_fields(False).build()

        request = SearchAppTableRecordRequest.builder() \
            .app_token(self.app_token) \
            .table_id(self.table_id) \
            .page_size(page_size) \
            .request_body(request_body) \
            .build()

        response = self.client.bitable.v1.app_table_record.search(request)

        if response.success():
            # 打印数据
            # console.print("Records:", lark.JSON.marshal(response.data, indent=2))
            
            # 保存数据到文件
            data_path = "./data/lark/latest.json"
            try:
                # 确保目录存在
                os.makedirs(os.path.dirname(data_path), exist_ok=True)
                with open(data_path, 'w', encoding='utf-8') as f:
                    f.write(lark.JSON.marshal(response.data, indent=2))
                console.print(f"[green]数据已保存到: {data_path}[/green]")
            except Exception as e:
                console.print(f"[red]保存数据失败: {str(e)}[/red]")
            
            return response.data
        else:
            console.print(f"[red]Failed to search records, code: {response.code}, msg: {response.msg}[/red]")
            return None

    def list_table_fields(self, page_size=20):
        from lark_oapi.api.bitable.v1 import ListAppTableFieldRequest

        request_builder = ListAppTableFieldRequest.builder() \
            .app_token(self.app_token) \
            .table_id(self.table_id) \
            .page_size(page_size)

        if self.view_id:
            request_builder = request_builder.view_id(self.view_id)

        request = request_builder.build()

        response = self.client.bitable.v1.app_table_field.list(request)

        if response.success():
            console.print("Fields:", lark.JSON.marshal(response.data, indent=4))
            return response.data
        else:
            console.print(f"[red]Failed to list fields, code: {response.code}, msg: {response.msg}[/red]")
            return None

    def update_record(self, record_id=None, fields_dict=None):
        request = UpdateAppTableRecordRequest.builder() \
            .app_token(self.app_token) \
            .table_id(self.table_id) \
            .record_id(record_id) \
            .request_body(
                AppTableRecord.builder()
                .fields(fields_dict)
                .build()
            ) \
            .build()

        response = self.client.bitable.v1.app_table_record.update(request)

        if response.success():
            # console.print("Update success:", lark.JSON.marshal(response.data, indent=4))
            return response.data
        else:
            console.print(f"[red]Failed to update record, code: {response.code}, msg: {response.msg}[/red]")
            return None

    def add_launch_to_bitable(self, launch: dict):
        """
        向多维表格新增一条火箭发射记录
        :param client: lark.Client 实例
        :param launch: dict，包含 date, time, mission, vehicle, pad, location, timestamp 字段
        """
        # 组装多维表格字段
        fields = {
            "Rocket Model": launch.get("vehicle", ""),
            "发射任务名称": launch.get("mission", ""),
            "发射位": launch.get("pad", ""),
            "发射日期时间": launch.get("timestamp", 0) * 1000  # 转为毫秒
        }

        request = CreateAppTableRecordRequest.builder() \
            .app_token(self.app_token) \
            .table_id(self.table_id) \
            .ignore_consistency_check(True) \
            .request_body(AppTableRecord.builder().fields(fields).build()) \
            .build()

        response = self.client.bitable.v1.app_table_record.create(request)
        if not response.success():
            lark.logger.error(
                f"新增失败, code: {response.code}, msg: {response.msg}, log_id: {response.get_log_id()}, resp: \n{json.dumps(json.loads(response.raw.content), indent=4, ensure_ascii=False)}")
            return False
        lark.logger.info(lark.JSON.marshal(response.data, indent=4))
        return True