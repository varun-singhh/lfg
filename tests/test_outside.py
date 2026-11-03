"""Read or write: the guard lets every command that only reads through, on every environment, and blocks what
changes something or cannot be classified (plugin/lib/lfgcore/outside.py, docs/guard-read-write.md)."""
import os
import sys
import tempfile
import unittest

# LFG code reads LFG_HOME when it is first imported: point it at a temp folder before anything imports it,
# whatever order the test files load in, so a test can never touch ~/.lfg
os.environ["LFG_HOME"] = tempfile.mkdtemp(prefix="lfg-test-home-")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "plugin", "lib"))
from lfgcore import guard, outside  # noqa: E402


def blocked(cmd):
    return guard.check("Bash", {"command": cmd})


class ReadsAreAlwaysAllowed(unittest.TestCase):
    def test_gcloud_run_reads_that_rule_15_used_to_block(self):
        self.assertIsNone(blocked("gcloud run services get-iam-policy my-svc --region us-central1"))
        self.assertIsNone(blocked("gcloud run services list --project atomus-deployments-prod-375300"))

    def test_impersonation_changes_nothing(self):
        flag = " --impersonate-service-account=lee-sa-prod@p.iam.gserviceaccount.com"
        self.assertIsNone(blocked("gcloud run services list" + flag))
        self.assertIsNotNone(blocked("gcloud run deploy svc --image x" + flag))

    def test_reads_on_other_systems(self):
        for cmd in ("aws s3 ls", "aws ec2 describe-instances --profile prod", "az vm list -g rg -o table",
                    "kubectl get pods -n prod", "gsutil ls gs://bucket", "bq query 'select 1'",
                    "supabase projects list", "gh api repos/o/r/pulls", "gcloud config list",
                    "clickhouse-client --query 'SELECT count(1) FROM t'", "psql -h db -c 'select 1'"):
            self.assertIsNone(blocked(cmd), cmd)

    def test_error_redirects_do_not_turn_a_read_into_an_unknown_command(self):
        for cmd in ("gcloud run services list 2>/dev/null", "gcloud run services list 2>&1",
                    "gcloud run services list --format=json 2>&1 | head -5",
                    "gcloud run services list > /tmp/out.txt 2>&1", "kubectl get pods &>/dev/null",
                    "aws s3 ls 2>/dev/null"):
            self.assertIsNone(blocked(cmd), cmd)
        self.assertIsNotNone(blocked("gcloud run deploy svc --image x 2>/dev/null"))
        self.assertIsNotNone(blocked("gcloud run services delete svc 2>&1"))

    def test_a_redirect_of_a_read_into_a_local_file_is_still_a_read(self):
        self.assertIsNone(blocked("gcloud run services list > /tmp/services.txt"))


class WritesAreBlocked(unittest.TestCase):
    def test_deploys_and_changes(self):
        for cmd in ("gcloud run deploy svc --image x", "gcloud run services update svc --image y",
                    "gcloud projects add-iam-policy-binding p --member=m --role=r", "aws s3 rm s3://b/k",
                    "az vm delete -g rg -n v", "kubectl apply -f x.yaml", "kubectl delete pod p",
                    "gsutil rm gs://b/k", "supabase db push", "supabase db reset --linked"):
            self.assertEqual(blocked(cmd)[0], "15", cmd)

    def test_unknown_commands_fail_toward_blocking(self):
        for cmd in ("gcloud frobnicate widgets", "aws made-up-service do-thing", "kubectl something-new",
                    "gcloud compute ssh vm -- list", "$CLI run"):
            self.assertIsNotNone(blocked(cmd), cmd)

    def test_a_read_piped_into_a_delete_is_a_write(self):
        self.assertIsNotNone(blocked("gcloud run services list --format='value(name)' | "
                                     "xargs -I{} gcloud run services delete {}"))
        self.assertIsNotNone(blocked("gcloud run services list | xargs gcloud run services delete"))

    def test_any_part_that_writes_makes_the_whole_command_a_write(self):
        for cmd in ("kubectl get pods && gcloud run deploy svc", "gcloud run services list; gcloud run deploy svc",
                    "echo $(gcloud run deploy svc)", "echo `gcloud run deploy svc`",
                    "bash -c 'gcloud run services list && gcloud run deploy svc'",
                    "for s in a b; do gcloud run services delete $s; done",
                    "find . -name x -exec gcloud run services delete {} " + chr(92) + ";"):
            self.assertIsNotNone(blocked(cmd), cmd)


class SecretValuesStayBlocked(unittest.TestCase):
    def test_reads_that_expose_a_secret(self):
        for cmd in ("gcloud secrets versions access latest --secret=s", "gcloud auth print-access-token",
                    "gcloud auth print-identity-token", "gcloud auth application-default print-access-token",
                    "aws secretsmanager get-secret-value --secret-id s",
                    "aws ssm get-parameter --name n --with-decryption", "aws sts get-session-token",
                    "az keyvault secret show --name n --vault-name v", "az account get-access-token",
                    "kubectl get secret s -o yaml", "kubectl config view --raw",
                    "supabase projects api-keys --project-ref x", "gh auth token", "gh auth status --show-token"):
            self.assertEqual(blocked(cmd)[0], "5", cmd)

    def test_secret_metadata_is_not_a_secret(self):
        for cmd in ("gcloud secrets list", "gcloud secrets describe s", "aws ssm get-parameter --name n",
                    "kubectl get pods", "gh secret list"):
            self.assertIsNone(blocked(cmd), cmd)


class SqlIsJudgedByItsStatements(unittest.TestCase):
    def kind(self, sql):
        return outside.sql_kind(sql)[0]

    def test_cte_hiding_an_update_is_a_write(self):
        sql = "WITH moved AS (UPDATE t SET a = 1 WHERE id = 2 RETURNING *) SELECT * FROM moved"
        self.assertEqual(self.kind(sql), outside.WRITE)
        self.assertEqual(blocked('psql -h db -c "%s"' % sql)[0], "11")

    def test_one_write_among_several_statements(self):
        self.assertEqual(self.kind("select 1; select 2; delete from t"), outside.WRITE)
        self.assertEqual(self.kind("select 1; select 2"), outside.READ)

    def test_keywords_inside_strings_and_comments_do_not_count(self):
        self.assertEqual(self.kind("select 'drop table t' as note -- delete from t"), outside.READ)
        self.assertEqual(self.kind("select replace(name, 'a', 'b') from t"), outside.READ)

    def test_other_ways_a_select_changes_things(self):
        for sql in ("select * into copy_t from t", "select nextval('s')", "select pg_terminate_backend(1)",
                    "select * from t for update", "explain analyze delete from t", "select 1 \\gexec",
                    "select 'unterminated"):
            self.assertEqual(self.kind(sql), outside.WRITE, sql)

    def test_clients_feed_from_every_source(self):
        self.assertIsNone(blocked("echo 'select 1' | psql -h db"))
        self.assertIsNotNone(blocked("echo 'drop table t' | psql -h db"))
        self.assertIsNotNone(blocked("cat file.sql | psql -h db"))  # unseen SQL is a write
        self.assertIsNone(blocked("psql -h db <<EOF\nselect 1;\nEOF"))
        self.assertIsNotNone(blocked("psql -h db <<EOF\ndelete from t;\nEOF"))
        self.assertIsNotNone(blocked("clickhouse-client -q 'INSERT INTO t VALUES (1)'"))

    @staticmethod
    def write(path, text):
        with open(path, "w") as f:
            f.write(text)

    def test_sql_files_are_read_and_judged(self):
        with tempfile.TemporaryDirectory() as d:
            ok, bad = os.path.join(d, "ok.sql"), os.path.join(d, "bad.sql")
            self.write(ok, "select 1;")
            self.write(bad, "select 1; update t set a = 1;")
            self.assertIsNone(blocked("psql -h db -f %s" % ok))
            self.assertIsNone(blocked("psql -h db < %s" % ok))
            self.assertIsNotNone(blocked("psql -h db -f %s" % bad))
            self.assertIsNotNone(blocked("psql -h db -f %s/missing.sql" % d))


class LocalDatabases(unittest.TestCase):
    def test_writes_to_your_own_machine_are_allowed(self):
        for cmd in ('psql -h localhost -c "delete from t"',
                    'psql postgresql://postgres:x@127.0.0.1:54322/postgres -c "drop table t"',
                    "psql -h localhost <<EOF\ndelete from t;\nEOF",
                    'clickhouse-client --host localhost -q "drop table t"'):
            self.assertIsNone(blocked(cmd), cmd)

    def test_anything_not_clearly_local_is_checked(self):
        for cmd in ('psql -h db.prod.example -c "delete from t"', 'psql -c "delete from t"',
                    'PGHOST=db psql -h localhost -c "delete from t"',
                    'psql -h localhost -h prod.example -c "delete from t"',
                    "psql -h prod <<EOF\ndelete from t;\nEOF"):
            self.assertIsNotNone(blocked(cmd), cmd)


class GhApiMethods(unittest.TestCase):
    def test_get_is_a_read_and_everything_else_is_a_write(self):
        self.assertIsNone(blocked("gh api repos/o/r/pulls"))
        self.assertIsNone(blocked("gh api -X GET repos/o/r/pulls"))
        for cmd in ("gh api -X POST repos/o/r/issues", "gh api --method=DELETE repos/o/r/git/refs/heads/x",
                    "gh api repos/o/r/issues -f title=x", "gh api repos/o/r/issues -F n=1",
                    "gh api repos/o/r/issues --input body.json",
                    "gh api graphql -f query='mutation { deleteRef(input: {}) { clientMutationId } }'"):
            self.assertEqual(blocked(cmd)[0], "2", cmd)


class McpTools(unittest.TestCase):
    def test_database_mcp_tools(self):
        self.assertIsNone(guard.check("mcp__clickhouse__run_select_query", {"query": "select 1"}))
        self.assertIsNone(guard.check("mcp__supabase__list_tables", {}))
        self.assertIsNone(guard.check("mcp__supabase__execute_sql", {"query": "select 1"}))
        self.assertIsNotNone(guard.check("mcp__supabase__execute_sql", {"query": "delete from t"}))
        self.assertIsNotNone(guard.check("mcp__supabase__apply_migration", {"name": "x", "query": "select 1"}))


if __name__ == "__main__":
    unittest.main()
