## Subagents

If the user explicitly asks you to spawn a subagent to answer a question, do this:

**Setup a scratch dir:**
```bash
mkdir /tmp/subagent
```

**Make the script that computes the response and streams it to stdout while it is being decoded:**

```bash
cat > /tmp/subagent/cmd.sh << OEF 
stdbuf -o0 -e0 pi --mode json "the question" | python3 -u ~/bin/pi_parse_stream.py | stdbuf -o0 -e0 tee /tmp/subagent/output.txt
OEF
chmod +x /tmp/subagent/cmd.sh
```

**Spawn it:**
```bash
tmux new-window -n "subagent" "/tmp/subagent/cmd.sh ; echo __DONE__ >> /tmp/subagent/output.txt"
```

Notice in the previous command there is a trainling double quote. Do not forget to emit it!

**Wait for result:**
```bash
while ! grep -q __DONE__ /tmp/subagent/output.txt; do sleep 2; done
cat /tmp/subagent/output.txt
```

Do not summarize the result, just emit it EXACTLY as it was (literally copy-paste it from inside /tmp/subagent/output.txt).

**Cleanup:**

Finally, cleanup the temp folder:

```bash
rm -rf /tmp/subagent/
```
