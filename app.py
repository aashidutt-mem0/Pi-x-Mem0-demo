"""
app.py - Streamlit demo: "Your coding agent forgets your schema conventions."

Scenario: extending a database schema. The Acme Checkout service ships a real
seeded schema (migrations/) whose house style is opinionated and NOT guessable:
PK is <entity>_id, money is BIGINT cents, soft deletes, FK ON DELETE RESTRICT,
paired up/down migrations. In Session 1 the developer states these conventions
and the @mem0/pi-agent-plugin captures them. In Session 2 - a fresh pi process -
the developer asks for a `refunds` table.

The demo runs Session 2 BOTH ways and shows them side by side:
  - NO MEMORY: vanilla pi guesses sensible-but-wrong defaults (SERIAL id,
    DECIMAL money, ON DELETE CASCADE, no down migration).
  - WITH MEMORY: pi loads the conventions from Mem0 and matches the house style.

A rule checker scores each migration so the win is concrete: broken code vs
correct code, not a wrong recital.

Run:
    export MEM0_API_KEY="m0-..."
    streamlit run app.py
"""

from __future__ import annotations

import difflib
import os

import streamlit as st

import pi_bridge as bridge
import sandbox
from checker import check_migration, score, extract_sql

# --------------------------------------------------------------------------- #
# Brand styling (Mem0: off-white bg, gold + purple accents, mono labels)
# --------------------------------------------------------------------------- #

MEM0_CSS = """
<style>
  :root {
    --offwhite:#FCFCFC; --softgrey:#E8E8E8; --border:#CCCCCC; --mid:#888888;
    --dark:#383838; --offblack:#181818; --gold:#F1C96C; --goldborder:#A68C51;
    --goldbg:#FAF1DE; --purple:#CBB2FF; --purplebg:#F4EEFF; --inset:#252525;
  }
  .stApp { background: var(--offwhite); }
  h1,h2,h3 { color: var(--offblack); font-weight:700; letter-spacing:-0.01em; }
  .mono { font-family:'DM Mono','SFMono-Regular',monospace; font-size:0.78rem;
          color:var(--mid); text-transform:uppercase; letter-spacing:0.08em; }
  .card { background:var(--softgrey); border:1px solid var(--border);
          border-radius:12px; padding:16px 18px; margin-bottom:12px; }
  .card-gold { background:var(--goldbg); border:1px solid var(--goldborder); }
  .card-purple { background:var(--purplebg); border:1px solid var(--purple); }
  .terminal { background:var(--inset); color:var(--offwhite);
              font-family:'DM Mono',monospace; font-size:0.78rem;
              border-radius:10px; padding:14px 16px; white-space:pre-wrap;
              line-height:1.45; overflow-x:auto; }
  .badge { display:inline-block; font-family:'DM Mono',monospace; font-size:0.7rem;
           padding:2px 8px; border-radius:6px; margin-right:6px; }
  .badge-gold { background:var(--gold); color:#54482C; }
  .badge-purple { background:var(--purple); color:#3A2E5C; }
  .badge-dim { background:var(--softgrey); color:var(--mid); border:1px solid var(--border); }
  .mem-line { padding:7px 11px; margin:5px 0; border-left:3px solid var(--gold);
              background:var(--goldbg); border-radius:0 6px 6px 0; font-size:0.86rem;
              color:var(--offblack); }
  .pass { color:#2f7d3b; font-weight:600; }
  .fail { color:#b3261e; font-weight:600; }
  .rule-row { padding:6px 10px; border-bottom:1px solid var(--border); font-size:0.86rem; }
</style>
"""

st.set_page_config(page_title="Pi x Mem0 - Schema Memory", layout="wide")
st.markdown(MEM0_CSS, unsafe_allow_html=True)


def readiness_panel():
    pi_ok = bridge.pi_available()
    mem_ok = bridge.mem0_available()
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(f"<span class='badge {'badge-gold' if pi_ok else 'badge-dim'}'>"
                    f"PI {'READY' if pi_ok else 'MISSING'}</span>", unsafe_allow_html=True)
        if not pi_ok:
            st.caption("Install: `curl -fsSL https://pi.dev/install.sh | sh`")
    with c2:
        st.markdown(f"<span class='badge {'badge-gold' if mem_ok else 'badge-dim'}'>"
                    f"MEM0 {'CONNECTED' if mem_ok else 'NO KEY/SDK'}</span>", unsafe_allow_html=True)
        if not mem_ok:
            st.caption("Set `MEM0_API_KEY` and `pip install mem0ai`")
    with c3:
        st.markdown("<span class='badge badge-purple'>@mem0/pi-agent-plugin</span>",
                    unsafe_allow_html=True)
    return pi_ok, mem_ok


def render_memory_panel(app_id: str):
    st.markdown("<div class='mono'>Project memory in Mem0 (live)</div>", unsafe_allow_html=True)
    mems = bridge.list_project_memories(app_id)
    if not mems:
        st.markdown("<div class='card'><i>Empty. The agent knows nothing about this "
                    "schema's conventions yet.</i></div>", unsafe_allow_html=True)
        return
    for m in mems:
        cats = ", ".join(m.get("categories") or []) if m.get("categories") else ""
        cat_html = f"<span class='badge badge-purple'>{cats}</span>" if cats else ""
        st.markdown(f"<div class='mem-line'>{cat_html}{m['memory']}</div>", unsafe_allow_html=True)


def render_rule_table(sql: str, title: str):
    results = check_migration(sql)
    passed, total = score(results)
    color = "pass" if passed == total else "fail"
    st.markdown(f"<b>{title}</b> &nbsp; <span class='{color}'>{passed}/{total} conventions honored</span>",
                unsafe_allow_html=True)
    rows = ""
    for r in results:
        icon = "<span class='pass'>PASS</span>" if r.passed else "<span class='fail'>FAIL</span>"
        rows += f"<div class='rule-row'>{icon} &nbsp; {r.label}</div>"
    st.markdown(f"<div class='card'>{rows}</div>", unsafe_allow_html=True)
    return passed, total


def render_diff(no_mem_sql: str, mem_sql: str):
    diff = difflib.unified_diff(
        no_mem_sql.splitlines(), mem_sql.splitlines(),
        fromfile="refunds.sql  (NO MEMORY)", tofile="refunds.sql  (WITH MEM0)",
        lineterm="",
    )
    lines = []
    for ln in diff:
        if ln.startswith("+") and not ln.startswith("+++"):
            lines.append(f"<span style='color:#7ee787'>{ln}</span>")
        elif ln.startswith("-") and not ln.startswith("---"):
            lines.append(f"<span style='color:#ff7b72'>{ln}</span>")
        elif ln.startswith("@@"):
            lines.append(f"<span style='color:#CBB2FF'>{ln}</span>")
        else:
            lines.append(ln)
    body = "\n".join(lines) if lines else "(identical)"
    st.markdown(f"<div class='terminal'>{body}</div>", unsafe_allow_html=True)


def main():
    st.title("Pi x Mem0 Demo")

    pi_ok, mem_ok = readiness_panel()
    st.divider()

    proj = sandbox.ensure_sandbox()
    app_id = sandbox.app_id_for(proj)
    st.markdown(f"<div class='mono'>sandbox repo: {proj} - app_id: {app_id}</div>",
                unsafe_allow_html=True)

    with st.expander("The existing schema the agent must match", expanded=False):
        for f in ["0001_create_orders.sql", "0002_create_line_items.sql"]:
            p = proj / "migrations" / f
            if p.exists():
                st.markdown(f"<div class='mono'>migrations/{f}</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='terminal'>{p.read_text()}</div>", unsafe_allow_html=True)

    with st.sidebar:
        st.markdown("### Demo controls")
        default_model = (
            "azure-openai-responses/gpt-5-mini"
            if os.environ.get("AZURE_OPENAI_API_KEY")
            else ""
        )
        model = st.text_input("Model (optional)", value=default_model,
                              placeholder=default_model or "anthropic/claude-sonnet-4-6")
        model_to_use = (model or default_model or None)
        st.divider()
        decision = st.text_area("Session 1 - conventions you state once",
                                value=sandbox.SCHEMA_CONVENTIONS, height=240)
        task = st.text_area("Session 2 - the task for the fresh process",
                            value="Add a refunds table. A refund belongs to an order "
                                  "and records how much was refunded and why. Write the "
                                  "migration.", height=120)
        st.divider()
        if st.button("Reset project memory", use_container_width=True):
            n = bridge.wipe_project_memories(app_id)
            st.success(f"Cleared {n} memories.")
            st.rerun()

    render_memory_panel(app_id)

    st.divider()

    disabled = not pi_ok or not mem_ok
    if not pi_ok:
        st.warning("Pi is not installed, so the live run is disabled. Layout still shows the flow.")
    elif not mem_ok:
        st.warning("Mem0 is not connected (need MEM0_API_KEY). The with-memory run is disabled.")

    run = st.button("Run the demo",
                    type="primary", disabled=disabled, use_container_width=True)

    if run:
        # SESSION 1: state conventions; plugin captures. Mirror into scope for determinism.
        s1_prompt = (f"{decision}\n\nAcknowledge these conventions briefly and remember "
                     f"them for future sessions. No code yet.")
        with st.spinner("Session 1 - stating the conventions..."):
            s1 = bridge.run_pi_session(s1_prompt, str(proj), model=model_to_use)
            if mem_ok and not s1.error:
                bridge.add_memory(decision, app_id)

        # SESSION 2A: fresh process, NO memory context. Force a clean guess.
        no_mem_prompt = (f"{task}\n\nOutput only the SQL migration in a ```sql code block.")
        with st.spinner("Session 2 (no memory) - fresh process guessing..."):
            s2_no = bridge.run_pi_session(no_mem_prompt, str(proj), model=model_to_use,
                                          inject_no_memory=True)

        # SESSION 2B: fresh process, WITH memory. Tell it to recall first.
        mem_prompt = (f"Before writing anything, recall this project's schema and migration "
                      f"conventions from memory. Then: {task}\n\nOutput only the SQL migration "
                      f"in a ```sql code block, following the recalled conventions exactly.")
        with st.spinner("Session 2 (with Mem0) - fresh process recalling conventions..."):
            s2_mem = bridge.run_pi_session(mem_prompt, str(proj), model=model_to_use)

        no_sql = extract_sql(s2_no.final_text)
        mem_sql = extract_sql(s2_mem.final_text)

        st.subheader("Generated refunds migrations")
        cby, cgold = st.columns(2)
        with cby:
            st.markdown("<span class='badge badge-dim'>SESSION 2 - NO MEMORY</span>",
                        unsafe_allow_html=True)
            st.markdown(f"<div class='terminal'>{no_sql or '(no SQL returned)'}</div>",
                        unsafe_allow_html=True)
        with cgold:
            st.markdown("<span class='badge badge-gold'>SESSION 2 - WITH MEM0</span>",
                        unsafe_allow_html=True)
            if s2_mem.memories_loaded:
                for q in s2_mem.memories_loaded:
                    st.caption(f"recalled: {q}")
            st.markdown(f"<div class='terminal'>{mem_sql or '(no SQL returned)'}</div>",
                        unsafe_allow_html=True)

        st.subheader("Convention checker")
        ccby, ccgold = st.columns(2)
        with ccby:
            p_no, t = render_rule_table(no_sql, "No memory")
        with ccgold:
            p_mem, _ = render_rule_table(mem_sql, "With Mem0")

        with st.expander("Diff", expanded=False):
            render_diff(no_sql, mem_sql)


if __name__ == "__main__":
    main()
