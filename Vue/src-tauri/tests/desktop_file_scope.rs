use std::path::PathBuf;
use tauri_plugin_fs::FsExt;

#[test]
fn dialog_file_grant_is_exact_and_does_not_survive_new_app() {
    let app = tauri::test::mock_builder()
        .plugin(tauri_plugin_fs::init())
        .build(tauri::test::mock_context(tauri::test::noop_assets()))
        .expect("mock application with official fs plugin");
    let fixtures = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent().unwrap()
        .join(".ai-workflow/20261010-desktop-delivery/scope-fixtures");
    std::fs::create_dir_all(&fixtures).unwrap();
    let opened = fixtures.join("chosen-[template].csv");
    let saved = fixtures.join("chosen-output.png");
    let sibling = fixtures.join("not-chosen.csv");
    std::fs::write(&opened, "source,illustrative,Fe_at%\nfrontend_demo,true,100\n").unwrap();
    std::fs::write(&sibling, "not authorized").unwrap();
    let scope = app.fs_scope();
    assert!(!scope.is_allowed(&opened));
    assert!(!scope.is_allowed(&saved));

    // These are the exact grants made by dialog 2.8.1 open/save after a file is selected.
    scope.allow_file(&opened).unwrap();
    scope.allow_file(&saved).unwrap();
    assert!(scope.is_allowed(&opened));
    assert!(scope.is_allowed(&saved));
    assert!(!scope.is_allowed(&sibling));
    assert!(!scope.is_allowed(&fixtures));
    assert!(!scope.is_allowed(fixtures.join("chosen-t.csv")));
    assert!(!scope.is_allowed(fixtures.join("child/other.csv")));

    let restarted = tauri::test::mock_builder()
        .plugin(tauri_plugin_fs::init())
        .build(tauri::test::mock_context(tauri::test::noop_assets()))
        .unwrap();
    assert!(!restarted.fs_scope().is_allowed(&opened));
    assert!(!restarted.fs_scope().is_allowed(&saved));
    println!("Actual official fs Scope: selected file allowed; siblings, parent, descendants denied; fresh application has no grants.");
}
