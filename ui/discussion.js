"use strict";

// Keep inspection on the selected historical stage as live calls arrive.
let inspectedSession = null, inspectedStage = null;
let replayTimer=null;
function stopReplay(){
  clearTimeout(replayTimer);
  replayTimer=null;
}
function playStages(record){
  const stages=stageHistory(record);
  const selected=stages.findIndex(stage=>stage.name===inspectedStage);
  let index=selected>=0 && selected<stages.length-1 ? selected : 0;
  function advance(){
    stopReplay();
    if(document.hidden || data.selected?.id!==record.id)return;
    inspectedStage=stages[index++].name;
    if(index<stages.length)replayTimer=setTimeout(advance,2100);
    renderDiscussion(data.selected);
    const art=$("conversation").querySelector(".map-art");
    if(art)enter(art);
  }
  advance();
}
function inspectPhase(index){
  const record=data.selected;
  const stage=record && stageHistory(record)[Number(index)];
  if(!stage)return;
  stopReplay();
  inspectedStage=stage.name;
  renderDiscussion(record);
  const map=$("conversation").querySelector(".map-art");
  if(map)enter(map);
}
function stageHistory(record) {
  const groups = new Map();
  for (const call of record.calls) {
    if (!groups.has(call.stage)) groups.set(call.stage, []);
    groups.get(call.stage).push(call);
  }
  return [...groups].map(([name, calls]) => ({name, calls}));
}
function voteOf(call) {
  if (!call.ended || call.error) return null;
  try {
    const v = JSON.parse(call.reply);
    return v?.reason?.trim() && ["accept", "object"].includes(v.vote) ? v.vote : null;
  } catch { return null; }
}
const shortStage = name => t(({
  "独立提案":"提案", "交叉评议":"互评", "候选方案":"拟稿", "表决":"表决",
  "最终方案撰写":"定稿", "图文 PDF 排版":"排版", "讨论总结":"总结"
})[name.replace(/ v\d+$/, "")] || name.replace(/ v\d+$/, "")) + (name.match(/ v\d+$/)?.[0] || "");

function stageMap(record) {
  const stages = stageHistory(record);
  const agents = [...new Set([...(record.seat_names || []), ...record.calls.map(c => c.agent)])].filter(a => Object.hasOwn(labels, a));
  const voters = record.seat_names?.length ? record.seat_names : agents;
  if (agents.length < 2 || !stages.length) return "";
  if (inspectedSession !== record.id) {
    inspectedSession = record.id;
    inspectedStage = null;
  }
  const latestVote = stages.map(s => s.name).filter(s => s.startsWith("表决")).at(-1);
  const preferred = inspectedStage || (!ongoing(record.state) && latestVote) || stages.at(-1).name;
  const index = Math.max(0, stages.findIndex(s => s.name === preferred));
  const stage = stages[index], voting = stage.name.startsWith("表决");
  const seats = agents.map(agent => {
    const attempts = stage.calls.filter(c => c.agent === agent);
    const call = attempts.at(-1);
    const vote = voting && call && voteOf(call);
    const state = !call ? "未调用" : call.error ? "已中断" : !call.ended ? "发言中" :
      vote === "accept" ? "赞成" : vote === "object" ? "有异议" : voting ? "无有效票" : "已发言";
    return {agent, call, state};
  });
  const replies = seats.filter(s => s.call?.ended && !s.call.error).length;
  const accepts = seats.filter(s => voters.includes(s.agent) && s.state === "赞成").length;
  const featured = seats.find(s => s.state==="有异议") || seats.find(s=>s.call?.reply && !s.call.error);
  const quote = featured && shortCall(featured.call);
  const glimpse = quote ? `<button class="stage-glimpse" data-read="call-${Number(featured.call.id)}"><b>${labels[featured.agent]}</b><span>${esc(quote.slice(0,78))}${quote.length>78?"…":""}</span>${icon("chevron")}</button>` : "";
  const positions = seats.length === 2 ? [[92,100],[328,100]] : [[92,127],[210,54],[328,127]];
  const controls = seats.map(({agent,call,state},i) => {
    const active = call ? ' data-read="call-'+Number(call.id)+'"' : ' disabled';
    return `<button type="button" class="map-seat slot-${i} ${agent}"${active} aria-label="${esc(labels[agent]+' · '+t(state))}"><span class="map-token">${glyph(agent)}</span><span class="map-label">${labels[agent]}<small>${t(state)}</small></span></button>`;
  }).join("");
  const lines = positions.map(([x,y],i) => {
    if (!seats[i].call) return "";
    const color = seats[i].state === "有异议" ? "#ffc681" : {codex:"#99e0d1",gemini:"#d1c6ff",claude:"#eaba91"}[seats[i].agent];
    return `<path class="map-trace" stroke="${color}" d="M${x} ${y} Q${x} 105 210 109"/>`;
  }).join("");
  const cross = stage.name === "交叉评议" ? positions.map(([x,y],i) => {
    const [toX,toY] = positions[(i+1)%positions.length];
    return seats[i].call ? `<path class="map-review-edge" d="M${x} ${y} Q210 ${i%2?150:15} ${toX} ${toY}"/>` : "";
  }).join("") : "";
  const ticks = Array.from({length:60},(_,i)=>{
    const a=i*Math.PI/30, major=i%5===0;
    return `M${210+157*Math.cos(a)} ${103+58*Math.sin(a)}l${(major?8:3)*Math.cos(a)} ${(major?4:1.6)*Math.sin(a)}`;
  }).join("");
  const center = voting ? (seats.some(s=>s.state==="有异议") ? "±" : accepts===voters.length ? "✓" : "…") :
    stage.name==="交叉评议" ? "⇄" : stage.name.startsWith("候选方案") ? "≡" : "◎";
  return `<section class="forum" data-key="round-map" aria-label="${t("讨论回放")}">
    <div class="forum-top"><h2><i class="forum-mark" aria-hidden="true"></i>${t("讨论回放")}</h2><label class="phase-select"><span aria-hidden="true">${t("阶段")} <b>${String(index+1).padStart(2,"0")}</b> / ${String(stages.length).padStart(2,"0")} ▾</span><select id="phaseSelect" aria-label="${t("选择阶段")}">${stages.map((step,i)=>`<option value="${i}" ${i===index?"selected":""}>${i+1} · ${esc(shortStage(step.name))}</option>`).join("")}</select></label></div>
    <div class="forum-body"><div class="forum-caption"><h3>${esc(displayStage(stage.name))}</h3>
      <p class="forum-count"><b>${voting?accepts:replies}</b><span>/ ${voting?voters.length:seats.filter(s=>s.call).length}</span></p>
      <p class="forum-measure">${t(voting?"席位赞成":"席位已回复")}</p>${glimpse}</div>
      <div class="map-art seats-${seats.length}">
        <svg viewBox="0 0 420 200" aria-hidden="true" focusable="false">
          <g fill="none" stroke="#7ba8aa"><ellipse opacity=".18" cx="210" cy="104" rx="187" ry="73" stroke-dasharray="2 6"/>
          <ellipse opacity=".23" cx="210" cy="111" rx="153" ry="56"/><ellipse fill="#254548" cx="210" cy="103" rx="153" ry="56"/>
          <ellipse cx="210" cy="103" rx="143" ry="51" opacity=".40"/><ellipse cx="210" cy="103" rx="99" ry="33" opacity=".28"/>
          <path opacity=".65" d="${ticks}"/><g data-key="routes-${index}">${lines}${cross}</g></g>
          <ellipse cx="210" cy="114" rx="28" ry="10" fill="#193436" stroke="#62868a"/>
          <ellipse cx="210" cy="108" rx="28" ry="12" fill="#304e50" stroke="#bfd7c9"/>
          <text x="210" y="113" text-anchor="middle" font-size="17" fill="#e1edd7">${center}</text>
        </svg>${controls}
      </div></div>
    <div class="forum-foot"><button type="button" id="playStages" aria-label="${t(replayTimer?"暂停回放":"播放回放")}" title="${t(replayTimer?"暂停回放":"播放回放")}" aria-pressed="${Boolean(replayTimer)}">${replayTimer?"Ⅱ":"▶"}</button><button class="map-step" data-phase-index="${index-1}" aria-label="${t("上一阶段")}" ${index===0?"disabled":""}>‹</button>
    <div class="phase-track" role="group" aria-label="${t("选择阶段")}">${stages.map((s,i)=>`<button type="button" data-phase-index="${i}" aria-pressed="${i===index}" class="${i<index?"passed":""}" title="${esc(displayStage(s.name))}" aria-label="${esc(displayStage(s.name))}"><i></i></button>`).join("")}</div>
    <button class="map-step" data-phase-index="${index+1}" aria-label="${t("下一阶段")}" ${index===stages.length-1?"disabled":""}>›</button></div></section>`;
}

function voteHistory(record){
  const rounds=stageHistory(record).filter(stage=>stage.name.startsWith("表决"));
  if(!rounds.length)return "";
  const agents=[...new Set(rounds.flatMap(stage=>stage.calls.map(c=>c.agent)))];
  const rows=rounds.map(stage=>{
    const votes=agents.map(agent=>{
      const call=stage.calls.filter(c=>c.agent===agent).at(-1);
      if(!call)return "<td>—</td>";
      const vote=voteOf(call);
      const label=vote==="accept"?"赞成":vote==="object"?"有异议":call.error?"已中断":call.ended?"无有效票":"等待回复…";
      return `<td><button class="ballot-mark ${vote||""}" data-read="call-${Number(call.id)}" aria-label="${esc(labels[agent]+" · "+displayStage(stage.name)+" · "+t(label))}">${vote==="accept"?"✓ ":vote==="object"?"− ":""}${t(label)}</button></td>`;
    }).join("");
    return "<tr><th scope='row'>"+esc(displayStage(stage.name))+"</th>"+votes+"</tr>";
  }).join("");
  return `<div class="ballot-history"><table><caption>${t("逐版表决")}</caption><thead><tr><th scope="col">${t("阶段")}</th>${agents.map(a=>'<th scope="col">'+esc(labels[a]||a)+'</th>').join("")}</tr></thead><tbody>${rows}</tbody></table></div>`;
}
function sessionDocuments(record) {
  const docs = [];
  const add = (key, name, text) => { if(text) docs.push({key,name:t(name),text}); };
  add("final","最终方案 · Gemini 执笔",finalDraft(record));
  add("summary","讨论总结",closingDraft(record));
  const approved = ["consensus","implementing","returned","inspect"].includes(record.state) || finalDraft(record) || record.workspace;
  add("plan",approved?"全体表决通过的原稿及分工":"候选方案",record.plan);
  const reports = record.calls.filter(c=>["实施","集成复核"].includes(c.stage) && c.reply);
  if(reports.length) docs.unshift({key:"reports",name:t("实施报告"),text:reports.map(c=>
    "## "+labels[c.agent]+" · "+displayStage(c.stage)+"\n\n"+readCall(c)).join("\n\n")});
  const reply = record.calls.filter(c=>c.stage==="单聊" && c.reply).at(-1);
  if(reply) add("reply","回复",reply.reply);
  return docs;
}
function readCall(call) {
  const text = call.reply || "";
  if(call.error) return [call.error, text].filter(Boolean).join("\n\n");
  if(call.stage.startsWith("表决")) return ballot(text);
  try {
    const structured=JSON.parse(text);
    if(typeof structured.report==="string")return structured.report;
    if(typeof structured.plan==="string")return structured.plan + (Array.isArray(structured.tasks)?
      "\n\n## "+t("任务分工")+"\n"+structured.tasks.map(task=>"\n- "+[task.owner,task.task,task.acceptance].filter(Boolean).join(" · ")).join(""):"");
  } catch {}
  return text || t("等待回复…");
}
function shortCall(call){
  const raw=call.reply || "";
  let text=raw;
  try{
    const obj=JSON.parse(raw);
    text=[obj.reason,obj.summary,obj.plan,obj.report,obj.items?.[0]?.claim].find(v=>typeof v==="string") || "";
  }catch{}
  return text.split("\n").map(s=>s.trim()).find(s=>s && !/^[#<{`|]/.test(s))?.replace(/^>\s*|\*\*/g,"") || "";
}
function documentCard(doc){
  const lines=doc.text.split("\n").map(s=>s.trim()).filter(Boolean);
  const title=lines[0]?.match(/^#\s+(.+)$/)?.[1];
  const paragraph=lines.find(s=>!s.startsWith("#") && !/^[-|`]/.test(s)) || lines[0] || "";
  const excerpt=paragraph.replace(/^>\s*/, "").replace(/\*\*|`/g,"");
  let fenced=false;
  const chapters=[];
  for(const line of lines){
    if(line.startsWith("```")){fenced=!fenced;continue;}
    const heading=!fenced && line.match(/^##\s+(.+)$/);
    if(heading && !chapters.includes(heading[1]))chapters.push(heading[1]);
    if(chapters.length===3)break;
  }
  const contents=chapters.length>1 ? `<nav class="cover-chapters" aria-label="${t("章节直达")}"><h3>${t("章节直达")}</h3>${chapters.map(name=>
    `<button data-read="${doc.key}" data-heading="${esc(name)}"><span>${inline(name)}</span>${icon("chevron")}</button>`).join("")}</nav>` : "";
  return `<article class="document-cover" data-key="result"><div class="cover-copy">${title?'<div class="doc-byline">'+icon("note")+esc(doc.name)+'</div>':""}
    <h2>${esc(title || doc.name)}</h2><p>${esc(excerpt.slice(0,145))}${excerpt.length>145?"…":""}</p>
    <button class="read-document" data-read="${doc.key}">${t("阅读全文")} ${icon("arrow")}</button></div>${contents}</article>`;
}
function docRow(doc){
  return `<button class="doc-row" data-key="doc-${doc.key}" data-read="${doc.key}"><span>${esc(doc.name)}</span></button>`;
}

let readerSession, readerTrigger, readerCall, returnScroll, readerSections=[];
function openReader(key, trigger) {
  if(replayTimer){stopReplay();renderDiscussion(data.selected);}
  const record=data.selected;
  if(!record)return;
  const dialog=$("reader");
  const docs=sessionDocuments(record);
  if(!dialog.open)readerCall=null;
  if(key.startsWith("call-"))readerCall=record.calls.find(c=>"call-"+c.id===key);
  if(readerCall){
    const callKey="call-"+readerCall.id, text=readCall(readerCall);
    docs.unshift({key:callKey,name:labels[readerCall.agent]+" · "+displayStage(readerCall.stage),text});
    if(readerCall.reply && readerCall.reply!==text)docs.push({key:"raw",name:t("原始发言"),text:readerCall.reply});
  }
  const doc=docs.find(d=>d.key===key);
  if(!doc)return;
  const opening=!dialog.open;
  if(opening){
    readerSession=record.id;readerTrigger=trigger;returnScroll=$("stage").scrollTop;
  }
  $("readerTitle").textContent=doc.name;
  const menu=$("readerDocs");
  menu.innerHTML='<option value="" disabled>'+t("切换文稿")+'</option>'+
    docs.map(d=>`<option value="${esc(d.key)}">${d.key===key?"✓ ":""}${esc(d.name)}</option>`).join("");
  menu.value="";
  menu.hidden=docs.length<2;
  const body=$("readerText");
  body.innerHTML=prose(doc.text);
  readerSections=[...body.querySelectorAll("h4,h5")];
  const outline=$("readerOutline");
  outline.innerHTML=readerSections.map((h,i)=>{
    h.id="reading-heading-"+i;
    return `<option value="${i}">${esc(h.textContent)}</option>`;
  }).join("");
  $("readerOutlineLabel").hidden=!readerSections.length;
  const nav=$("readerNav");
  nav.hidden=!readerSections.length;
  nav.innerHTML=readerSections.map((h,i)=>`<button data-chapter="${i}" class="${h.tagName==="H5"?"nested":""}">${esc(h.textContent)}</button>`).join("");
  if(!dialog.open)dialog.showModal();
  $("readerScroll").scrollTop=0;
  updateReading();
  if(opening)$("readerClose").focus({preventScroll:true});
  const heading=trigger?.dataset.heading;
  if(heading && trigger?.dataset.read===key){
    const tmp=document.createElement("span");
    tmp.innerHTML=inline(heading);
    const index=readerSections.findIndex(h=>h.textContent===tmp.textContent);
    if(index>=0)jumpChapter(index);
  }
  enter(body);
}
function updateReading(){
  const box=$("readerScroll"), offset=box.getBoundingClientRect().top+28;
  const range=box.scrollHeight-box.clientHeight;
  $("readerProgress").value=range?Math.min(100,100*box.scrollTop/range):100;
  if(!readerSections.length)return;
  let index=readerSections.findIndex(h=>h.getBoundingClientRect().top>offset)-1;
  if(index===-2)index=readerSections.length-1;
  index=Math.max(0,index);
  $("readerOutline").value=String(index);
  const nav=$("readerNav"), active=nav.children[index];
  if(active && !active.hasAttribute("aria-current")){
    nav.querySelector("[aria-current]")?.removeAttribute("aria-current");
    active.setAttribute("aria-current","location");
    if(active.offsetTop<nav.scrollTop || active.offsetTop+active.offsetHeight>nav.scrollTop+nav.clientHeight){
      nav.scrollTop=active.offsetTop-nav.clientHeight/3;
    }
  }
}
function jumpChapter(index) {
  readerSections[index]?.scrollIntoView({block:"start",behavior:"instant"});
  updateReading();
}
