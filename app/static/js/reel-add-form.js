document.addEventListener("change", (event) => {
    if (!event.target.matches('select[name="location_id"]')) {
        return;
    }
    const form = event.target.closest(".reel-add-form");
    const fields = form && form.querySelector(".new-location-fields");
    if (fields) {
        fields.hidden = event.target.value !== "__new__";
    }
});
