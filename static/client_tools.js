window.exportDataToExcel = function(data, filename) {
    if (typeof XLSX === 'undefined') return customAlert("Библиотека XLSX не загружена");
    const ws = XLSX.utils.json_to_sheet(data);
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "Реестр");
    XLSX.writeFile(wb, filename + ".xlsx");
};

window.openClientCard = function(id) {
    const client = clientsDB.find(c => c.id === id);
    if(!client) return;
    
    const cProjs = projectsDB.filter(p => (p.client || '').includes(client.name));
    const cClaims = claimsDB.filter(c => (c.addressee || '').includes(client.name) || (c.initiator || '').includes(client.name) || cProjs.some(p => p.id === c.proj_id));
    const cCourts = courtCasesDB.filter(c => (c.plaintiff || '').includes(client.name) || (c.defendant || '').includes(client.name) || cProjs.some(p => p.id === c.proj_id));

    let html = `<div style="display:flex; gap:20px; flex-wrap:wrap;">
        <div style="flex:1; min-width:250px; background:var(--bg); padding:15px; border-radius:12px; border:1px solid var(--border);">
            <h4 style="margin-top:0; color:var(--primary); display:flex; justify-content:space-between;">Сделки <span>${cProjs.length}</span></h4>
            ${cProjs.length === 0 ? '<span style="font-size:12px; color:var(--secondary);">Нет сделок</span>' : cProjs.map(p => `<div style="font-size:12px; margin-bottom:8px; padding-bottom:8px; border-bottom:1px dashed var(--border);"><a href="#" onclick="openProject(${p.id}); document.getElementById('clientCardModal').style.display='none';"><b>${p.contract}</b></a><br><span style="color:var(--secondary)">Сумма:</span> ${Number(p.budget || 0).toLocaleString('ru-RU')} ₽<br><span style="color:var(--secondary)">Статус:</span> ${p.status}</div>`).join('')}
        </div>
        <div style="flex:1; min-width:250px; background:var(--bg); padding:15px; border-radius:12px; border:1px solid var(--danger);">
            <h4 style="margin-top:0; color:var(--danger); display:flex; justify-content:space-between;">Претензии <span>${cClaims.length}</span></h4>
            ${cClaims.length === 0 ? '<span style="font-size:12px; color:var(--secondary);">Нет претензий</span>' : cClaims.map(c => `<div style="font-size:12px; margin-bottom:8px; padding-bottom:8px; border-bottom:1px dashed var(--danger);"><b style="color:var(--danger)">№${c.number}</b><br><span style="color:var(--secondary)">Сумма:</span> ${Number(c.amount || 0).toLocaleString('ru-RU')} ₽<br><span style="color:var(--secondary)">Статус:</span> ${c.status}</div>`).join('')}
        </div>
        <div style="flex:1; min-width:250px; background:var(--bg); padding:15px; border-radius:12px; border:1px solid #8b5cf6;">
            <h4 style="margin-top:0; color:#8b5cf6; display:flex; justify-content:space-between;">Суды <span>${cCourts.length}</span></h4>
            ${cCourts.length === 0 ? '<span style="font-size:12px; color:var(--secondary);">Нет судов</span>' : cCourts.map(c => `<div style="font-size:12px; margin-bottom:8px; padding-bottom:8px; border-bottom:1px dashed #8b5cf6;"><b style="color:#8b5cf6">${c.number}</b><br><span style="color:var(--secondary)">Сумма:</span> ${Number(c.amount || 0).toLocaleString('ru-RU')} ₽<br><span style="color:var(--secondary)">Стадия:</span> ${c.stage}</div>`).join('')}
        </div>
    </div>`;

    let modal = document.getElementById('clientCardModal');
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'clientCardModal';
        modal.className = 'modal-overlay';
        modal.style.zIndex = '10005';
        modal.innerHTML = `
            <div class="modal-card" style="max-width: 1000px; width: 95%;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 20px;">
                    <h2 id="clientCardTitle" style="margin:0;"></h2>
                    <button class="btn-danger" onclick="document.getElementById('clientCardModal').style.display='none'">✕</button>
                </div>
                <div style="font-size:13px; color:var(--secondary); margin-bottom: 20px; background:var(--bg); padding:10px; border-radius:8px;">
                    ИНН: <b id="clientCardInn" style="color:var(--text)"></b> | Контакт: <b id="clientCardContact" style="color:var(--text)"></b>
                </div>
                <div id="clientCardContent" class="client-card-scroll"></div>
            </div>`;
        document.body.appendChild(modal);
    }
    document.getElementById('clientCardTitle').innerText = `Досье контрагента: ${client.name}`;
    document.getElementById('clientCardInn').innerText = client.inn || 'Не указан';
    document.getElementById('clientCardContact').innerText = client.contact || 'Не указан';
    document.getElementById('clientCardContent').innerHTML = html;
    modal.style.display = 'flex';
};
