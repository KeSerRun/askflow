"""知识库管理用例测试（sqlite 临时库 + 假向量库/对象存储，免外部依赖）。"""

import shutil
import tempfile
import time
import unittest

from core.app_errors import InvalidInput, NotFound
from core.models import Document
from infra.adapters.storage import SqliteRepo
from modules.database.service import DatabaseService


class FakeVector:
    """假向量库：记录 partition / source，支持统计与删除。"""

    def __init__(self):
        self.rows: list[dict] = []
        self.available = True

    def is_available(self) -> bool:
        return self.available

    @property
    def metadata(self) -> list[dict]:
        return list(self.rows)

    def get_partitions(self) -> list[str]:
        return sorted({r["partition"] for r in self.rows if r.get("partition")})

    def add_documents(self, docs) -> None:
        for d in docs:
            m = dict(d.metadata or {})
            m.setdefault("text", d.page_content)
            self.rows.append(m)

    def delete_by_sources(self, sources, partition=None) -> None:
        names = set(sources or [])
        self.rows = [
            r for r in self.rows
            if r.get("source") not in names
            or (partition and r.get("partition") != partition)
        ]

    def delete_by_doc_ids(self, ids) -> None:
        ids = set(ids or [])
        self.rows = [r for r in self.rows if r.get("id") not in ids]

    def count(self) -> int:
        return len(self.rows)


class FakeDocService:
    """假文档服务：记录 upload 调用（分区, 文件名）。"""

    def __init__(self):
        self.uploaded: list[tuple[str, str]] = []

    @staticmethod
    def sanitize_filename(raw: str) -> str:
        return raw

    def upload(self, partition: str, filename: str, data: bytes) -> None:
        self.uploaded.append((partition, filename))

    def purge(self, *a, **k) -> None:
        pass


class KnowledgeBaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.repo = SqliteRepo(f"sqlite:///{self.tmp}/kb.sqlite3")
        self.vector = FakeVector()
        self.docs = FakeDocService()
        self.svc = DatabaseService(
            self.vector, self.docs, repo=self.repo, object_store=None, parent_store=None,
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _seed_vector(self, partition: str, source: str, text: str = "内容") -> None:
        self.vector.add_documents([Document(
            page_content=text,
            metadata={"partition": partition, "source": source, "chunk_type": "text"},
        )])

    # ── 知识库目录建表 ──

    def test_knowledge_bases_table_registered(self):
        """knowledge_bases 表随仓储初始化自动建出（无需手工迁移）。"""
        self.svc.create_knowledge_base("表检查", "d")
        rows = self.repo.find("knowledge_bases")
        self.assertEqual([r.id for r in rows], ["表检查"])

    # ── 创建 ──

    def test_create_and_list(self):
        self.svc.create_knowledge_base("产品手册", "收录产品说明")
        items = self.svc.list_knowledge_bases()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["name"], "产品手册")
        self.assertEqual(items[0]["description"], "收录产品说明")
        self.assertEqual(items[0]["chunks"], 0)          # 空库也必须可见
        self.assertEqual(items[0]["documents"], 0)
        self.assertTrue(items[0]["managed"])

    def test_create_duplicate_rejected(self):
        self.svc.create_knowledge_base("A")
        with self.assertRaises(InvalidInput):
            self.svc.create_knowledge_base("A")

    def test_invalid_names_rejected(self):
        for bad in ("", "   ", "a/b", 'a"b', "a\\b", "x" * 65, "a;b", "a b"):
            with self.assertRaises(InvalidInput, msg=f"{bad!r} 应被拒绝"):
                self.svc.create_knowledge_base(bad)

    def test_valid_names_accepted(self):
        for good in ("产品手册", "a-b_c", "KB2024", "知识库-1"):
            self.svc.create_knowledge_base(good)
        self.assertEqual(len(self.svc.list_knowledge_bases()), 4)

    # ── 更新 ──

    def test_rename(self):
        self.svc.create_knowledge_base("旧库", "d")
        self.svc.update_knowledge_base("旧库", new_name="新库")
        self.assertEqual([k["name"] for k in self.svc.list_knowledge_bases()], ["新库"])

    def test_rename_collision_rejected(self):
        self.svc.create_knowledge_base("A")
        self.svc.create_knowledge_base("B")
        with self.assertRaises(InvalidInput):
            self.svc.update_knowledge_base("A", new_name="B")

    def test_rename_missing_kb_raises(self):
        with self.assertRaises(NotFound):
            self.svc.update_knowledge_base("不存在", new_name="X")

    def test_update_description_only(self):
        self.svc.create_knowledge_base("库")
        self.svc.update_knowledge_base("库", description="新描述")
        self.assertEqual(self.svc.list_knowledge_bases()[0]["description"], "新描述")

    def test_rename_invalid_name_rejected(self):
        self.svc.create_knowledge_base("库")
        with self.assertRaises(InvalidInput):
            self.svc.update_knowledge_base("库", new_name="bad/name")

    # ── 删除 ──

    def test_delete_removes_vectors_and_record(self):
        self.svc.create_knowledge_base("库A")
        self._seed_vector("库A", "doc.pdf")
        self.svc.delete_knowledge_base("库A")
        self.assertEqual(self.vector.rows, [])
        self.assertEqual(self.svc.list_knowledge_bases(), [])

    def test_delete_only_touches_target_kb(self):
        self.svc.create_knowledge_base("A")
        self.svc.create_knowledge_base("B")
        self._seed_vector("A", "a.pdf")
        self._seed_vector("B", "b.pdf")
        self.svc.delete_knowledge_base("A")
        self.assertEqual([r["source"] for r in self.vector.rows], ["b.pdf"])

    def test_delete_unknown_kb_still_removes_orphan_vectors(self):
        """未登记的遗留分区也能被清理。"""
        self._seed_vector("legacy", "old.pdf")
        self.svc.delete_knowledge_base("legacy")
        self.assertEqual(self.vector.rows, [])

    # ── 统计 ──

    def test_stats_reflect_vectors(self):
        self.svc.create_knowledge_base("A")
        self._seed_vector("A", "a.pdf")
        self._seed_vector("A", "b.pdf")
        item = self.svc.list_knowledge_bases()[0]
        self.assertEqual(item["documents"], 2)
        self.assertEqual(item["chunks"], 2)

    def test_legacy_partition_listed_unmanaged(self):
        self._seed_vector("__system__", "old.pdf")
        items = self.svc.list_knowledge_bases()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["name"], "__system__")
        self.assertFalse(items[0]["managed"])

    def test_list_survives_vector_outage(self):
        """向量库不可用时目录仍可列出（chunks 记 0）。"""
        self.svc.create_knowledge_base("A")
        self.vector.available = False
        items = self.svc.list_knowledge_bases()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["chunks"], 0)

    def test_create_works_without_vector_store(self):
        """向量库未起也能创建知识库。"""
        self.vector.available = False
        self.svc.create_knowledge_base("无向量库")
        self.assertEqual(len(self.svc.list_knowledge_bases()), 1)

    # ── 上传必须归属知识库 ──

    def test_upload_requires_existing_kb(self):
        with self.assertRaises(InvalidInput):
            self.svc.upload_system([("a.pdf", b"%PDF", "application/pdf")], "不存在")

    def test_upload_requires_partition(self):
        with self.assertRaises(InvalidInput):
            self.svc.upload_system([("a.pdf", b"%PDF", "application/pdf")], "")

    def test_upload_targets_selected_kb(self):
        self.svc.create_knowledge_base("库B")
        res = self.svc.upload_system([("a.pdf", b"%PDF", "application/pdf")], "库B")
        for _ in range(100):
            task = self.svc.upload_task(res["task_id"])
            if task["status"] != "processing":
                break
            time.sleep(0.02)
        self.assertEqual(self.docs.uploaded, [("库B", "a.pdf")])
        self.assertEqual(task["success"], 1)

    def test_upload_task_records_partition(self):
        self.svc.create_knowledge_base("库C")
        res = self.svc.upload_system([("a.pdf", b"%PDF", "application/pdf")], "库C")
        self.assertEqual(res["task_id"], self.svc.upload_task(res["task_id"])["id"])

    # ── 文档列表按知识库隔离（回归：曾写死 __system__ 导致新库文档不显示） ──

    def test_list_system_docs_scoped_by_partition(self):
        self.svc.create_knowledge_base("库X")
        self.svc.create_knowledge_base("库Y")
        self._seed_vector("库X", "x.pdf")
        self._seed_vector("库Y", "y.pdf")

        names_x = [d["name"] for d in self.svc.list_system_docs(partition="库X")["documents"]]
        names_y = [d["name"] for d in self.svc.list_system_docs(partition="库Y")["documents"]]
        self.assertEqual(names_x, ["x.pdf"])
        self.assertEqual(names_y, ["y.pdf"])

    def test_list_system_docs_without_partition_returns_all(self):
        self.svc.create_knowledge_base("库X")
        self.svc.create_knowledge_base("库Y")
        self._seed_vector("库X", "x.pdf")
        self._seed_vector("库Y", "y.pdf")
        names = [d["name"] for d in self.svc.list_system_docs()["documents"]]
        self.assertEqual(sorted(names), ["x.pdf", "y.pdf"])

    def test_list_docs_does_not_leak_other_kb_vectors(self):
        """库 X 不应看到库 Y 的文档。"""
        self.svc.create_knowledge_base("库X")
        self.svc.create_knowledge_base("库Y")
        self._seed_vector("库Y", "y.pdf")
        self.assertEqual(self.svc.list_system_docs(partition="库X")["documents"], [])

    def test_md_view_missing_product_returns_reason(self):
        """文档视图按分区找产物；分区不对时给出可读原因而非崩溃。"""
        self.svc.create_knowledge_base("库X")
        res = self.svc.md_view("missing.pdf", "库X")
        self.assertFalse(res["available"])
        self.assertIn("middle_json", res["reason"])

    # ── 已入库文档：跨库 + 独立搜索 + 知识库字段 ──

    def test_list_system_docs_reports_owning_partition(self):
        """不指定分区时，跨库文档各自带上所属知识库。"""
        self.svc.create_knowledge_base("库X")
        self.svc.create_knowledge_base("库Y")
        self._seed_vector("库X", "x.pdf")
        self._seed_vector("库Y", "y.pdf")
        by_name = {d["name"]: d for d in self.svc.list_system_docs()["documents"]}
        self.assertEqual(by_name["x.pdf"]["partitions"], ["库X"])
        self.assertEqual(by_name["y.pdf"]["partitions"], ["库Y"])
        self.assertEqual(by_name["x.pdf"]["partition"], "库X")

    def test_list_system_docs_same_name_in_two_kbs(self):
        """同名文档分布在多个库时，partitions 列出全部。"""
        self.svc.create_knowledge_base("库X")
        self.svc.create_knowledge_base("库Y")
        self._seed_vector("库X", "same.pdf")
        self._seed_vector("库Y", "same.pdf")
        docs = self.svc.list_system_docs()["documents"]
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["partitions"], ["库X", "库Y"])
        self.assertEqual(docs[0]["chunks"], 2)

    def test_list_system_docs_keyword_by_filename(self):
        self.svc.create_knowledge_base("库X")
        self._seed_vector("库X", "年报.pdf")
        self._seed_vector("库X", "合同.pdf")
        res = self.svc.list_system_docs(keyword="年")
        self.assertEqual([d["name"] for d in res["documents"]], ["年报.pdf"])
        self.assertEqual(res["total"], 1)

    def test_list_system_docs_keyword_by_partition(self):
        """关键词也能按知识库名命中。"""
        self.svc.create_knowledge_base("产品手册")
        self.svc.create_knowledge_base("法务资料")
        self._seed_vector("产品手册", "a.pdf")
        self._seed_vector("法务资料", "b.pdf")
        res = self.svc.list_system_docs(keyword="产品")
        self.assertEqual([d["name"] for d in res["documents"]], ["a.pdf"])

    def test_list_system_docs_keyword_case_insensitive(self):
        self._seed_vector("库X", "Annual Report.pdf")
        self.assertEqual(
            self.svc.list_system_docs(keyword="annual")["total"], 1)
        self.assertEqual(self.svc.list_system_docs(keyword="ANNUAL")["total"], 1)

    def test_list_system_docs_keyword_and_partition_combined(self):
        self.svc.create_knowledge_base("库X")
        self.svc.create_knowledge_base("库Y")
        self._seed_vector("库X", "x.pdf")
        self._seed_vector("库Y", "y.pdf")
        res = self.svc.list_system_docs(partition="库Y", keyword="y")
        self.assertEqual([d["name"] for d in res["documents"]], ["y.pdf"])

    def test_list_system_docs_keyword_no_match(self):
        self._seed_vector("库X", "x.pdf")
        self.assertEqual(self.svc.list_system_docs(keyword="zzz")["documents"], [])

    def test_delete_scoped_to_partition(self):
        """跨库视图下删除只清理指定库，同名文档在别的库保留。"""
        self.svc.create_knowledge_base("库X")
        self.svc.create_knowledge_base("库Y")
        self._seed_vector("库X", "same.pdf")
        self._seed_vector("库Y", "same.pdf")
        self.svc.delete("same.pdf", "库X")
        self.assertEqual([(r["partition"], r["source"]) for r in self.vector.rows],
                         [("库Y", "same.pdf")])

    # ── 分页 + 模糊搜索 ──

    def _seed_many(self, n: int = 12):
        for i in range(n):
            self.svc.create_knowledge_base(f"库{i:02d}", f"第 {i} 号知识库的说明")

    def test_pagination_envelope(self):
        self._seed_many(12)
        page = self.svc.list_knowledge_bases_page(page=1, page_size=5)
        self.assertEqual(page["total"], 12)
        self.assertEqual(page["page"], 1)
        self.assertEqual(page["page_size"], 5)
        self.assertEqual(len(page["knowledge_bases"]), 5)

    def test_pagination_second_page(self):
        self._seed_many(12)
        page = self.svc.list_knowledge_bases_page(page=2, page_size=5)
        self.assertEqual(len(page["knowledge_bases"]), 5)
        names_1 = [k["name"] for k in self.svc.list_knowledge_bases_page(page=1, page_size=5)["knowledge_bases"]]
        names_2 = [k["name"] for k in page["knowledge_bases"]]
        self.assertFalse(set(names_1) & set(names_2), "两页不应有重复")

    def test_pagination_page_size_zero_returns_all(self):
        self._seed_many(7)
        page = self.svc.list_knowledge_bases_page(page=1, page_size=0)
        self.assertEqual(len(page["knowledge_bases"]), 7)

    def test_pagination_out_of_range_is_empty(self):
        self._seed_many(3)
        page = self.svc.list_knowledge_bases_page(page=9, page_size=5)
        self.assertEqual(page["knowledge_bases"], [])
        self.assertEqual(page["total"], 3)

    def test_search_by_name(self):
        self._seed_many(12)
        res = self.svc.list_knowledge_bases(keyword="库03")
        self.assertEqual([k["name"] for k in res], ["库03"])

    def test_search_by_description(self):
        self.svc.create_knowledge_base("产品手册", "收录 2024 年产品说明与参数表")
        self.svc.create_knowledge_base("法律法规", "合同模板与规章制度")
        res = self.svc.list_knowledge_bases(keyword="参数表")
        self.assertEqual([k["name"] for k in res], ["产品手册"])

    def test_search_case_insensitive(self):
        self.svc.create_knowledge_base("KB2024", "Annual Report")
        res = self.svc.list_knowledge_bases(keyword="annual")
        self.assertEqual([k["name"] for k in res], ["KB2024"])

    def test_search_partial_name(self):
        self.svc.create_knowledge_base("产品手册")
        self.svc.create_knowledge_base("产品路线图")
        res = self.svc.list_knowledge_bases(keyword="产品")
        self.assertEqual(len(res), 2)

    def test_search_no_match_empty(self):
        self._seed_many(3)
        self.assertEqual(self.svc.list_knowledge_bases(keyword="不存在的库"), [])

    def test_search_combined_with_pagination(self):
        self._seed_many(12)
        page = self.svc.list_knowledge_bases_page(page=1, page_size=3, keyword="库")
        self.assertEqual(page["total"], 12)
        self.assertEqual(len(page["knowledge_bases"]), 3)

    def test_search_blank_is_noop(self):
        self._seed_many(4)
        self.assertEqual(len(self.svc.list_knowledge_bases(keyword="")), 4)
        self.assertEqual(len(self.svc.list_knowledge_bases(keyword="   ")), 4)


if __name__ == "__main__":
    unittest.main()
