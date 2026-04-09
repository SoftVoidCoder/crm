let html5QrcodeScanner;

function openScanner() {
    document.getElementById('scannerModal').style.display = 'flex';
    
    // Инициализация сканера (запрашивает доступ к камере)
    html5QrcodeScanner = new Html5QrcodeScanner("qr-reader", { 
        fps: 10, 
        qrbox: { width: 250, height: 250 },
        rememberLastUsedCamera: true
    }, false);
    
    html5QrcodeScanner.render(onScanSuccess, onScanFailure);
}

function closeScanner() {
    if (html5QrcodeScanner) {
        html5QrcodeScanner.clear();
    }
    document.getElementById('scannerModal').style.display = 'none';
}

function onScanSuccess(decodedText, decodedResult) {
    console.log("QR scanned:", decodedText);
    try {
        const data = JSON.parse(decodedText);
        
        if (data.type === 'doc' && data.id) {
            // Успешно распознали наш документ!
            closeScanner();
            
            // Переключаемся в раздел канцелярии, чтобы подгрузить базу
            navigateTo('documents'); 
            
            // Даем долю секунды на отрисовку интерфейса и открываем карточку
            setTimeout(() => {
                openPrintDoc(data.id);
            }, 300);
        } else {
            customAlert("QR-код распознан, но он не принадлежит нашей системе.");
        }
    } catch(e) {
        customAlert("Неизвестный формат QR-кода: " + decodedText);
    }
}

function onScanFailure(error) {
    // Ошибки сканирования происходят каждый кадр, пока код не найден. Просто игнорируем.
}

// Функция открытия печатной формы документа из любого места
window.openPrintDoc = function(id) {
    const d = documentsDB.find(x => x.id === id);
    if (!d) {
        customAlert("Документ не найден в базе.");
        return;
    }
    
    document.getElementById('printDocTitle').innerText = `Документ № ${d.number}`;
    document.getElementById('printDocDate').innerText = d.d_date || 'Не указана';
    document.getElementById('printDocCorr').innerText = d.correspondent || 'Не указан';
    document.getElementById('printDocSubj').innerText = d.subject || '';
    
    const qrImg = document.getElementById('printDocQr');
    if (d.qr_code) {
        qrImg.src = d.qr_code;
        qrImg.style.display = 'block';
    } else {
        qrImg.style.display = 'none';
    }
    
    document.getElementById('printDocModal').style.display = 'flex';
};