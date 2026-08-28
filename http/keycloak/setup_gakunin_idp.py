#!/usr/bin/env python3
"""realm `mcp` に「学認（GakuNin）SAML ブローカ」を足す。

`keycloak-trial/setup-saml-idp.sh`（realm jairo 向け・Keycloak 24）の移植版。
本 PoC は issuer をホスト／コンテナで同一文字列に揃えてあるので、
front-channel と back-channel で URL を出し分ける必要が無く素直に書ける。

期待できる属性は次の3つだけ、という前提で組む。

  学認 機関 IdP から  … eduPersonPrincipalName (eppn) **のみ**
  学認 mAP から       … isMemberOf **のみ**
  所属（機関）        … 属性ではなく **SAML アサーションの Issuer**
                        （＝機関 IdP の entityID）から決める

`eduPersonScopedAffiliation` は機関の属性リリースポリシー次第で降ってこないし、
mail も同様。一方 **Issuer は必ず存在し、しかも署名検証済み**なので、
「どの機関の利用者か」の判定根拠としてはこちらの方が強い。

  realm `gakunin`  … モック機関 IdP（学認の DS + 機関 IdP の代役）
      └ SAML client = realm `mcp` のブローカが名乗る SP
        属性リリース: eduPersonPrincipalName / isMemberOf のみ
  realm `mcp`      … OIDC AS 兼 SAML SP
      ├ identity provider `gakunin`（SAML）
      ├ Username Template Importer: eppn を Keycloak のユーザ名にする
      ├ 属性インポータ: eppn → `eppn`, isMemberOf → `is_member_of`
      ├ Hardcoded Attribute: `idp_entity_id` = Issuer（entityID）
      ├ Hardcoded Attribute: `tenant_id`     = Issuer から引いた機関コード
      └ client scope `federation`（realm 既定）… 上記を**アクセストークンのクレーム**に出す
        ＋ user session note `identity_provider` → クレーム `idp`（そのセッションで
          実際に使われた IdP。保存属性と違い「最後のログイン」に汚染されない）

Issuer → 機関コードの対応表は **こちら（JAIRO Cloud 側）が持つ registry** で、
Keycloak では「IdP alias ごとの Hardcoded Attribute」がその実体になる。
IdP を1つ登録するたびに entityID と機関コードを1行足す運用。

mAP について（重要・PoC の割り切り）:
  本来 GakuNin mAP のグループ属性は、ブローカが eppn をキーに **API で引く**もの
  （図のフェーズ2）。Keycloak でこれを本当にやるには custom authenticator/mapper の
  SPI（Java）か、ログイン後の属性同期ジョブが要る。本 PoC では mAP 由来の
  `isMemberOf` を**モック IdP の SAML アサーションに載せて代替**し、
  「トークンにグループが載って RS まで届く」ところだけを実証する。
  学認 SAML ブローカの追加は任意。keycloak モードを使わないなら不要。
"""
import os
import sys

# 同じディレクトリの setup_mcp_realm を使う（実行時の cwd に依存しない）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import setup_mcp_realm as S  # noqa: E402

REALM = S.REALM
IDP_REALM = "gakunin"
ALIAS = "gakunin"
DISPLAY = "学認 (GakuNin)"

IDP_USER = "gakunin-user"
IDP_PASS = "Gakunin1!"
EPPN = "hanako@example.ac.jp"
IS_MEMBER_OF = "https://example.ac.jp/groups/repository-editors"

# 機関 IdP の entityID（＝ SAML アサーションの Issuer）。
# Keycloak は identity provider の `idpEntityId` と突き合わせて検証するので、
# ここに書いた値と一致するアサーションしか通らない。
IDP_ENTITY_ID = f"{S.KC}/realms/{IDP_REALM}"

# Issuer → 機関コードの registry（JAIRO Cloud 側が持つ対応表）。
# 実運用では「学認に SP 登録した機関 IdP の entityID」を鍵にする。
TENANT_BY_ISSUER = {
    IDP_ENTITY_ID: "example-univ",
}

# 学認でよく使う OID（今回使うのは eppn と isMemberOf だけ）
OID = {
    "eppn": "urn:oid:1.3.6.1.4.1.5923.1.1.1.6",
    "isMemberOf": "urn:oid:1.3.6.1.4.1.5923.1.5.1.1",
}

BROKER_SP_ENTITY = f"{S.KC}/realms/{REALM}"
BROKER_ACS = f"{S.KC}/realms/{REALM}/broker/{ALIAS}/endpoint"


def saml_attr_mapper(client_uuid, name, oid, friendly, source=None, hardcoded=None):
    if hardcoded is not None:
        mapper, cfg = "saml-hardcode-attribute-mapper", {"attribute.value": hardcoded}
    else:
        mapper, cfg = "saml-user-property-mapper", {"user.attribute": source}
    cfg.update({
        "attribute.name": oid,
        "friendly.name": friendly,
        "attribute.nameformat": "URI Reference",
    })
    S.post(
        f"/admin/realms/{IDP_REALM}/clients/{client_uuid}/protocol-mappers/models",
        {"name": name, "protocol": "saml", "protocolMapper": mapper, "config": cfg},
    )


def idp_mapper(name, mapper, config):
    cfg = dict(config)
    cfg.setdefault("syncMode", "FORCE")
    S.post(
        f"/admin/realms/{REALM}/identity-provider/instances/{ALIAS}/mappers",
        {"name": name, "identityProviderAlias": ALIAS,
         "identityProviderMapper": mapper, "config": cfg},
    )


def idp_attr_importer(name, oid, friendly, user_attribute):
    idp_mapper(name, "saml-user-attribute-idp-mapper", {
        "attribute.name": oid,
        "attribute.friendly.name": friendly,
        "user.attribute": user_attribute,
    })


def idp_hardcoded(name, attribute, value):
    """Issuer に紐づく固定値を利用者属性として刻む。

    「どの IdP のアサーションで入ってきたか」は Keycloak が署名と idpEntityId で
    検証済みなので、alias ごとの固定値＝**検証済み Issuer 由来の情報**になる。
    """
    idp_mapper(name, "hardcoded-attribute-idp-mapper",
               {"attribute": attribute, "attribute.value": value})


def claim_mapper(scope_id, name, user_attribute, claim):
    S.post(
        f"/admin/realms/{REALM}/client-scopes/{scope_id}/protocol-mappers/models",
        {
            "name": name,
            "protocol": "openid-connect",
            "protocolMapper": "oidc-usermodel-attribute-mapper",
            "config": {
                "user.attribute": user_attribute,
                "claim.name": claim,
                "jsonType.label": "String",
                "access.token.claim": "true",
                "id.token.claim": "true",
                "userinfo.token.claim": "true",
                "introspection.token.claim": "true",
                "multivalued": "true",
            },
        },
    )


def disable_review_profile():
    """初回ブローカログインの「Update Account Information」画面を出さない。

    IdP 側の `updateProfileFirstLoginMode` は新しめの Keycloak では効かず、
    `first broker login` フローの Review Profile 実行部の
    `update.profile.on.first.login` を off にするのが確実。
    学認では属性が IdP から降ってくるので、利用者に入力させる必要が無い。
    """
    execs = S.get(f"/admin/realms/{REALM}/authentication/flows/first%20broker%20login/executions") or []
    for e in execs:
        if e.get("providerId") != "idp-review-profile":
            continue
        cfg_id = e.get("authenticationConfig")
        if cfg_id:
            S.put(f"/admin/realms/{REALM}/authentication/config/{cfg_id}", {
                "id": cfg_id, "alias": "review profile config",
                "config": {"update.profile.on.first.login": "off"},
            })
        else:
            S.post(f"/admin/realms/{REALM}/authentication/executions/{e['id']}/config", {
                "alias": "review profile config",
                "config": {"update.profile.on.first.login": "off"},
            })
        print("  first broker login: Review Profile を off（属性は IdP 由来で自動登録）")
        return
    print("  ! Review Profile の実行部が見つからない", file=sys.stderr)


def allow_identifier_only_users():
    """「識別子しか無い利用者」を認可サーバが受け入れられるようにする。

    学認から降ってくるのが eppn だけの場合、Keycloak は既定のままだと
      * 宣言的ユーザプロファイルで email / firstName / lastName を必須扱い
      * required action `VERIFY_PROFILE` で入力画面を出す
    となり、**エージェントの認可フローが人手入力で止まる**。
    連合が識別子しか渡さない前提なら、必須指定を外すのが正しい設定。
    """
    profile = S.get(f"/admin/realms/{REALM}/users/profile")
    if profile:
        for attr in profile.get("attributes", []):
            if attr.get("name") in ("email", "firstName", "lastName"):
                attr.pop("required", None)
        S.put(f"/admin/realms/{REALM}/users/profile", profile)
        print("  ユーザプロファイル: email / 氏名 の必須指定を解除")

    for ra in S.get(f"/admin/realms/{REALM}/authentication/required-actions") or []:
        if ra.get("alias") == "VERIFY_PROFILE":
            S.put(f"/admin/realms/{REALM}/authentication/required-actions/VERIFY_PROFILE",
                  {**ra, "enabled": False, "defaultAction": False})
            print("  required action VERIFY_PROFILE: 無効化")


def main():
    S.T = S.admin_token()

    # --- モック機関 IdP realm -------------------------------------------
    if S.get(f"/admin/realms/{IDP_REALM}"):
        S.delete(f"/admin/realms/{IDP_REALM}")
    S.post("/admin/realms", {
        "realm": IDP_REALM, "enabled": True,
        "displayName": f"{DISPLAY} モック機関 IdP", "sslRequired": "none",
    })
    print(f"realm {IDP_REALM}: 作成（モック機関 IdP）")

    cuuid = S.post(f"/admin/realms/{IDP_REALM}/clients", {
        "clientId": BROKER_SP_ENTITY,       # ブローカが SP として名乗る entityID
        "protocol": "saml", "enabled": True,
        "redirectUris": [BROKER_ACS],
        "attributes": {
            "saml_assertion_consumer_url_post": BROKER_ACS,
            "saml.assertion.signature": "true",
            "saml.server.signature": "true",
            "saml.client.signature": "false",
            "saml_name_id_format": "username",
            "saml.authnstatement": "true",
        },
    })
    print(f"  SAML client（= realm {REALM} のブローカ SP）: 作成")

    # 機関 IdP から期待できるのは eppn だけ、という前提でリリースする。
    # mail / 氏名 / eduPersonScopedAffiliation は**わざと出さない**。
    saml_attr_mapper(cuuid, "eduPersonPrincipalName", OID["eppn"], "eduPersonPrincipalName",
                     hardcoded=EPPN)
    # ↓ mAP 由来。本来はブローカが eppn をキーに API で引く（PoC ではアサーションで代替）
    saml_attr_mapper(cuuid, "isMemberOf", OID["isMemberOf"], "isMemberOf",
                     hardcoded=IS_MEMBER_OF)
    print("  属性リリース: eppn（機関 IdP）/ isMemberOf（mAP 相当）のみ")

    # 機関側は氏名もメールも**持っている**が、属性リリースポリシーで出さない。
    # （上の protocol-mapper に mail / givenName / sn を作っていないのがその表現）
    # モック IdP 自身が Keycloak なので、ローカルには値を入れておかないと
    # VERIFY_PROFILE の required action で止まってしまう。
    S.post(f"/admin/realms/{IDP_REALM}/users", {
        "username": IDP_USER, "enabled": True,
        "email": "hanako@example.ac.jp", "emailVerified": True,
        "firstName": "花子", "lastName": "学認",
        "credentials": [{"type": "password", "value": IDP_PASS, "temporary": False}],
    })
    print(f"  IdP テストユーザ {IDP_USER}: 作成（値は持つが SP には出さない）")

    # --- 署名証明書を取り出して realm mcp に SAML IdP を登録 ---------------
    # realm には RSA 鍵が複数ある（RS256/SIG と RSA-OAEP/ENC）。証明書は両方に付くので
    # 「最初の RSA」で取ると**暗号用の鍵**を掴んで署名検証が Invalid signature になる。
    # 必ず use=SIG かつ ACTIVE の署名鍵を選ぶ。
    keys = S.get(f"/admin/realms/{IDP_REALM}/keys")
    cert = next(k["certificate"] for k in keys["keys"]
                if k.get("type") == "RSA" and k.get("use") == "SIG"
                and k.get("status") == "ACTIVE" and k.get("certificate"))

    S.delete(f"/admin/realms/{REALM}/identity-provider/instances/{ALIAS}")
    S.post(f"/admin/realms/{REALM}/identity-provider/instances", {
        "alias": ALIAS, "displayName": DISPLAY, "providerId": "saml",
        "enabled": True, "trustEmail": True,
        "config": {
            "singleSignOnServiceUrl": f"{S.KC}/realms/{IDP_REALM}/protocol/saml",
            "entityId": BROKER_SP_ENTITY,
            "idpEntityId": f"{S.KC}/realms/{IDP_REALM}",
            "nameIDPolicyFormat": "urn:oasis:names:tc:SAML:1.1:nameid-format:unspecified",
            "postBindingResponse": "true", "postBindingAuthnRequest": "true",
            "validateSignature": "true", "wantAssertionsSigned": "false",
            "signingCertificate": cert, "wantAuthnRequestsSigned": "false",
            # 属性は下でインポートするので初回ログインの確認画面は出さない
            "updateProfileFirstLoginMode": "off",
        },
    })
    print(f"realm {REALM}: SAML identity provider '{ALIAS}' 登録")

    # 再実行時は realm gakunin を作り直す＝IdP の署名鍵が変わるので、
    # 前回のブローカ済みユーザが残っていると `idp-confirm-link` 画面に落ちる。
    # 冪等にするため消しておく（ユーザ名は eppn）。
    for u in S.get(f"/admin/realms/{REALM}/users?username={EPPN}&exact=true") or []:
        S.delete(f"/admin/realms/{REALM}/users/{u['id']}")
        print(f"  前回のブローカ済みユーザ {u['username']} を削除（再実行の冪等化）")

    # eppn を Keycloak のユーザ名にする（NameID は機関によって transient なので当てにしない）
    idp_mapper("eppn-as-username", "saml-username-idp-mapper", {
        "template": "${ATTRIBUTE." + OID["eppn"] + "}", "target": "LOCAL",
    })
    idp_attr_importer("eppn", OID["eppn"], "eduPersonPrincipalName", "eppn")
    idp_attr_importer("ismemberof", OID["isMemberOf"], "isMemberOf", "is_member_of")
    # 所属は属性ではなく **Issuer（検証済みの機関 IdP entityID）** から決める
    idp_hardcoded("issuer-entity-id", "idp_entity_id", IDP_ENTITY_ID)
    idp_hardcoded("issuer-to-tenant", "tenant_id", TENANT_BY_ISSUER[IDP_ENTITY_ID])
    print(f"  属性インポータ: eppn / is_member_of")
    print(f"  Issuer 由来: idp_entity_id={IDP_ENTITY_ID}")
    print(f"               tenant_id={TENANT_BY_ISSUER[IDP_ENTITY_ID]}")

    disable_review_profile()
    allow_identifier_only_users()

    # --- 連合属性をアクセストークンのクレームに出す client scope ----------
    scopes = S.get(f"/admin/realms/{REALM}/client-scopes") or []
    for s in scopes:
        if s["name"] == "federation":
            S.delete(f"/admin/realms/{REALM}/client-scopes/{s['id']}")
    sid = S.post(f"/admin/realms/{REALM}/client-scopes", {
        "name": "federation",
        "description": "学認由来の連合属性（eppn / Issuer 由来の所属 / mAP のグループ）",
        "protocol": "openid-connect",
        "attributes": {"include.in.token.scope": "false"},
    })
    claim_mapper(sid, "eppn", "eppn", "eppn")                       # 機関 IdP 由来
    claim_mapper(sid, "is_member_of", "is_member_of", "isMemberOf")  # mAP 由来
    claim_mapper(sid, "idp_entity_id", "idp_entity_id", "idp_entity_id")  # Issuer そのもの
    claim_mapper(sid, "tenant_id", "tenant_id", "tenant_id")         # Issuer から引いた機関コード
    # 保存属性は「最後にログインした IdP」で上書きされる。そのセッションで実際に
    # 使われた IdP は user session note の方が正確なので、別クレームで併記する。
    S.post(f"/admin/realms/{REALM}/client-scopes/{sid}/protocol-mappers/models", {
        "name": "idp-session-note",
        "protocol": "openid-connect",
        "protocolMapper": "oidc-usersessionmodel-note-mapper",
        "config": {
            "user.session.note": "identity_provider",
            "claim.name": "idp",
            "jsonType.label": "String",
            "access.token.claim": "true",
            "id.token.claim": "true",
            "introspection.token.claim": "true",
        },
    })
    # realm 既定（default）にする → **これから**登録されるクライアントに自動で付く
    S.put(f"/admin/realms/{REALM}/default-default-client-scopes/{sid}", {})
    # realm 既定は「新規作成されるクライアント」にしか効かない。
    # mcp-server / invenio-api は先に作られているので個別に付ける。
    # これを忘れると **トークン交換した先（InvenioRDM 宛トークン）に連合属性が載らない**。
    for c in S.get(f"/admin/realms/{REALM}/clients") or []:
        if c["clientId"] in ("mcp-server", "invenio-api"):
            S.put(f"/admin/realms/{REALM}/clients/{c['id']}/default-client-scopes/{sid}", {})
    print("client scope federation: realm 既定 + 既存クライアントに付与"
          "（eppn / isMemberOf / idp_entity_id / tenant_id / idp）")

    print("\n--- 確認 ---")
    idps = S.get(f"/admin/realms/{REALM}/identity-provider/instances") or []
    for i in idps:
        print(f"  IdP: {i['alias']} ({i['displayName']}) providerId={i['providerId']}")
    print(f"  ブローカ ACS: {BROKER_ACS}")
    print(f"  Issuer (機関 IdP entityID): {IDP_ENTITY_ID}")
    print(f"  テストユーザ: {IDP_USER} / {IDP_PASS}  eppn={EPPN}")
    print("  ※ この IdP は mail も氏名も出さない（eppn と isMemberOf のみ）")


if __name__ == "__main__":
    main()
