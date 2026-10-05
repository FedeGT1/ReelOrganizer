window.patchMultiPlaceResolution = function (selectEl, key) {
    const row = selectEl.closest(".multi-place-row");
    const hiddenInput = row.querySelector('input[name="place_json"]');
    const data = JSON.parse(hiddenInput.value);
    data[key] = selectEl.value;
    hiddenInput.value = JSON.stringify(data);
};
