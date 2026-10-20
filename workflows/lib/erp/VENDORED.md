# VENDORED: the ERP read module

This folder is an exact copy of the read parts of the canonical ERP module.
It is never edited here. A change goes to the canonical module first, then a
new copy replaces this folder and this file.

| | |
|---|---|
| Canonical module | `hubzoid/order-desk-hub:erp/` (`erp.CANONICAL` retains the legacy module name) |
| Source commit | `a3c3993135ebffa2c291dac3a7780be46f7bf796` |
| Copied on | 20 Oct 2026 |
| Left out | `write.py`, `digest.py`, `bootstrap.py`: the write contract. The Customer Desk never writes to ERPNext and mounts no ERP write tool |

The desk reaches this module only through `workflows/lib/customer_desk/erpnext/`,
which refuses `writes_enabled: true` and always passes a customer `party_scope`.
`tests/test_vendored_erp.py` checks every byte against the table below and every
dataset file against `datasets/distributor-v1/manifest.json`.

Coordinated canonical update: `service.py` and `config.py` include the 20 October build's SDK data-root and first-initialization fixes from the Order Desk worktree. `service.py` also rejects a configured data root while legacy ERP state still exists, before allocating a new deployment identity. The exact canonical commit is recorded above; it includes the initial reviewed implementation and the necessary identity guard author fix. No write contract was copied.

## Files

| File | SHA-256 |
|---|---|
| `README.md` | `sha256:5cbe8a6d957572cda68c762e6a126e87ac156c86ba180ecf1e8ebd3aab9a0723` |
| `__init__.py` | `sha256:de7b71650d0e1b4fefe30c1f41282b13641e077a62acbeb17402aff2d90fe956` |
| `backends/__init__.py` | `sha256:8184e60bb7d4c9fd43c7ab7d1a268021122208bc07bfc3394aed191e16583a2f` |
| `backends/frappe_rest.py` | `sha256:989015e88488f10ee3e10b1fafcbc9d113ac63d9e5924efb016d9686df46bd90` |
| `backends/sample.py` | `sha256:26a89ea856f0ddef57434fea7429e086d89f2b5b04c17b20fede9c22b0417a8d` |
| `cli.py` | `sha256:588b58e9eda9542ddee66dbfe35dcb0f7e575ffa5860c4e585c2349c2b13547a` |
| `config.py` | `sha256:973f383d933e622128490d81ea850104effd50c213f859164ff2b826048c1529` |
| `datasets/__init__.py` | `sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `datasets/distributor-v1/README.md` | `sha256:55699122a9bd24dd44e9e7b4ed9cd6da9bc183e3daeffc255035e161ee772892` |
| `datasets/distributor-v1/attachments/AH-3315.pdf` | `sha256:90ddf4a609481de7856c298f76ab391cd635604cc0b474436b5054b90c090881` |
| `datasets/distributor-v1/attachments/GCS-3002.png` | `sha256:e0c557d259d694444b39066d463326568d865e54ac590bb270788245d96659c0` |
| `datasets/distributor-v1/attachments/GCS-3003.pdf` | `sha256:fb50c595f23f481d9589ee7cc1f9351543e90438138ccde2eaca81ce663ac28e` |
| `datasets/distributor-v1/attachments/HF-7011.png` | `sha256:7ce962fce83b903c713e2090a5ce7133c7b3625897426b0a5358849b27033b48` |
| `datasets/distributor-v1/attachments/PC-0050.xlsx` | `sha256:e6d6d67d00465dec79d56b40715e36e24a5b430105468b982907afeeebe1a3d6` |
| `datasets/distributor-v1/attachments/PC-0051.pdf` | `sha256:6cafc414c7e22804357ea691cb3594a2bcb895b8801bf76dd01aab1fbbef2b1b` |
| `datasets/distributor-v1/attachments/SNP-INV-0912.pdf` | `sha256:090ea40e08c6d68b17a219e178845d8cf03dbdfb06a3b785e62d95963b4db85b` |
| `datasets/distributor-v1/attachments/SNP-INV-0913.xlsx` | `sha256:646495e841a22aebc637b97787ca7cbcb9596bddf5b9229e5297f42c4d8f6ba7` |
| `datasets/distributor-v1/attachments/SNP-INV-0960.pdf` | `sha256:db1846231cccd2e76cc4b56f60d0d4676a455260d72600f0e9cd8e4de535357e` |
| `datasets/distributor-v1/attachments/SSB-2003.pdf` | `sha256:638e12b352df4d9d836756492231f18a6ef8edcb2faffe52b338decb0af6aa6d` |
| `datasets/distributor-v1/bindings.csv` | `sha256:8c3b7472bf86c54e3ac08de3d3fb585761c5c18e11c76ffb7d0eb37c2e2ffdf9` |
| `datasets/distributor-v1/erp/bins.json` | `sha256:43dba6f56978f46de9a2bce21306f6e0991f8f75d090f76889eea839894607d7` |
| `datasets/distributor-v1/erp/company.json` | `sha256:19e60b8f2b259851f290afb2a728998686341415761ed9441801154bb82d2ea6` |
| `datasets/distributor-v1/erp/contacts.json` | `sha256:3b9ce27b268dd513e63ab519a8624d06bbf9100606b30be0b884b73979702541` |
| `datasets/distributor-v1/erp/customers.json` | `sha256:e691898c5c4c5aa09b13b78177e74f15173081f19cfd681ef6af7f13a095038d` |
| `datasets/distributor-v1/erp/item_prices.json` | `sha256:81c39b274a601214b6a33d1d2d65020939fb52e7b050f4eb05e3c8ccc93a2e98` |
| `datasets/distributor-v1/erp/items.json` | `sha256:f111958ac4b29133c735fd20abf5bf95fc2e22101c7995f20c2183f4bd920ea4` |
| `datasets/distributor-v1/erp/price_lists.json` | `sha256:579ccd1b4b00d537a06df87c079c71120dbe16272ddc0eb357bf0eef36a0884c` |
| `datasets/distributor-v1/erp/purchase_invoices.json` | `sha256:184fac430e7e8c43ab67fe57742fb902f9f7326f4652554e2f30e6b427a6d1fd` |
| `datasets/distributor-v1/erp/purchase_orders.json` | `sha256:78b120bf34aa2d7ce5a9bab255ad98c2f37909c0dfa6159f67f9d79de3acadcc` |
| `datasets/distributor-v1/erp/purchase_receipts.json` | `sha256:1b27bc8adbf04a214551664debc3e8d0acf657f38bca657258ee3969f4caa707` |
| `datasets/distributor-v1/erp/sales_invoices.json` | `sha256:ad82a6ec380024365f2fe23e81a8d4cee5859c49f9b1bab9f2a92d11cd825d6b` |
| `datasets/distributor-v1/erp/sales_orders.json` | `sha256:96f5752bd58de24a64bd3672ce0d515301f5d3d5b88d20b502f18174e290a7c5` |
| `datasets/distributor-v1/erp/suppliers.json` | `sha256:0fc8bc5e8d64c37407dab875c4aef555f3dd74110fe54e00183f5583bc51d313` |
| `datasets/distributor-v1/erp/uoms.json` | `sha256:f521b31202343a4c5642be4d851a1fee25fc62c6407f1e752c664bacf86f2f56` |
| `datasets/distributor-v1/erp/warehouses.json` | `sha256:690938a0817cc24bcad1fa90185985b1d63ba07e1c08a4c92dcc1ec6c37519e0` |
| `datasets/distributor-v1/expected/order-invoice-desk.json` | `sha256:2dfa2a4b95e006a08ad501e478418f878e8800293a04ed8941634f11284ad95d` |
| `datasets/distributor-v1/manifest.json` | `sha256:089f2fe5e341b21636271ba4093fd4751bb2c1b412cd3821f5485e4cad23e77f` |
| `datasets/distributor-v1/messages/customer-desk-adversarial.jsonl` | `sha256:a1ce356a2c9b50a6f09b70d8d1a4dcd0273ddd5fd51efb8a11177aa938bf2012` |
| `datasets/distributor-v1/messages/customer-desk.index.json` | `sha256:2d0c5a79870a058d52cef913e872a607b50e05b6f6f09e6f0e36325a28bd5a86` |
| `datasets/distributor-v1/messages/customer-desk.jsonl` | `sha256:6ce021ea4211373a6a2ba1503f1c2b93f934ccd8c8b98f8bad4ec5ea29b68140` |
| `datasets/distributor-v1/messages/order-invoice-desk-adversarial.jsonl` | `sha256:2011774e69e08bb7b3e3b473d398fe3f07b51b9909abd8509ee8de57fc801728` |
| `datasets/distributor-v1/messages/order-invoice-desk-extras.jsonl` | `sha256:86dd873241148b875fe5b6ea25e56296fadab7705e215966422433d1a27f3613` |
| `datasets/distributor-v1/messages/order-invoice-desk.jsonl` | `sha256:5197a6e43e1e68a38ccfdd8fb8d80f3a08ff3ec219de343c68bd4d966902ba8f` |
| `datasets/distributor-v1/print/ACC-SINV-2000-00001.pdf` | `sha256:651f6c6f8ff6f51f64bb9a73c054a8629bfcf4f05703b9003b59ea0ef66be538` |
| `datasets/distributor-v1/print/ACC-SINV-2000-00002.pdf` | `sha256:743f0ccc7bcc1f8300795df41ead56114c5a1c345ddf5e2946ce69a6357dec95` |
| `datasets/distributor-v1/print/ACC-SINV-2000-00003.pdf` | `sha256:3f1554e017a25fb50be85ee82893b615e1644c845382c9138077f2ff5f5d7b84` |
| `datasets/distributor-v1/print/ACC-SINV-2000-00004.pdf` | `sha256:cdc08fe8663ba60b6a87c8ee20e006e408ec1e5deca8df9a8b784bc1efc61b91` |
| `datasets/distributor-v1/raw/CD-001.eml` | `sha256:8e51b7bff9d948fcbfa6f37640afd34eeb77aa58c8327891cae302b45fd70abb` |
| `datasets/distributor-v1/raw/CD-002.eml` | `sha256:a20c08ce227185953e1f5b424f473042e507bed4f7ee8a1594d3dfa069e0a0d3` |
| `datasets/distributor-v1/raw/CD-003.eml` | `sha256:f8584263c226d9ac71f5b9d26259c1d4258322526a1fbb0e1e6e218230f89c81` |
| `datasets/distributor-v1/raw/CD-004.eml` | `sha256:c142e99e5af7d8811f31e0fde5ac440b8c24e43308a4550bea44ba0f29bb7480` |
| `datasets/distributor-v1/raw/CD-005.whatsapp.json` | `sha256:2e883aa9dee6c2dcff9e8a30d70b226dd173f54f58c8c859a9b0a3e1f7787fd0` |
| `datasets/distributor-v1/raw/CD-006.eml` | `sha256:231d9a72c0b6a49cd70d474e8948101ebfb9938fd4f1b07a847abd2cce3e915f` |
| `datasets/distributor-v1/raw/CD-007.eml` | `sha256:49e7eb16fe4cb7616d780ccd0493f55875427fe58a06a83e99575867552385f9` |
| `datasets/distributor-v1/raw/CD-008.eml` | `sha256:268372c105d57f236725fd0d234fc849736d14ebbd78b1b8c89cc9aa2dfe5cd9` |
| `datasets/distributor-v1/raw/CD-009.eml` | `sha256:26cd0969ac33306f240a3450741d363f59dbf89d82dc572d2d421c06354459c2` |
| `datasets/distributor-v1/raw/CD-010.whatsapp.json` | `sha256:7a3c988105202a9dc3134f912a608edf63a143eba513d37037df8aa04d2d197b` |
| `datasets/distributor-v1/raw/CD-011.eml` | `sha256:7d1952113e7407aced23f7c69eba7ea670bd213a78704c793dfe65d393b671f2` |
| `datasets/distributor-v1/raw/CD-012.eml` | `sha256:389a7b4dc67e10ee54a2444fc45cc1629f590594f3c7a261d91fd5b90b79c37c` |
| `datasets/distributor-v1/raw/CD-013.eml` | `sha256:036a1808c56dcd51b3c9c6e589bde8dc8635646ff4f6f32d258fddbad99ae8f6` |
| `datasets/distributor-v1/raw/CD-014.whatsapp.json` | `sha256:828f9b3d1c0b45ec3a5c664b89a36060c45fe72d60071f4230ad4af9b5c98510` |
| `datasets/distributor-v1/raw/CD-015.eml` | `sha256:3097faceeebe8de5a4c860d8ae3aea2d911aace02eec314300352438e7a57e14` |
| `datasets/distributor-v1/raw/CD-016.eml` | `sha256:e10f881d442533272de3fdc73f57d26bd45276028086ec4acf03a6e697d64769` |
| `datasets/distributor-v1/raw/CD-017.eml` | `sha256:02cc55532d6ba47b98cb6df3238cd27c0ae58ec2d04ec75118538bce0a85fdb5` |
| `datasets/distributor-v1/raw/CD-018.eml` | `sha256:439ffd431353f89b03a3f6fbb3e8e40f571969daa5f8845c93f0e34e54b7deff` |
| `datasets/distributor-v1/raw/CD-019.whatsapp.json` | `sha256:a26a15c1567c99fa28c67a8ad02b39b1c867da9718ab5fb196630ccd63598fdb` |
| `datasets/distributor-v1/raw/CD-020.eml` | `sha256:ea2ba31edb575e60501171685857a021021980b64f8d68a90dd8c82ae61f5d3b` |
| `datasets/distributor-v1/raw/CD-A01.eml` | `sha256:5cc5e41e71a3b2bed8a380d4aa0b50f992ebcaac82fc1c01a1f6573dbd6ddd9a` |
| `datasets/distributor-v1/raw/CD-A02.eml` | `sha256:30dde9c1357464ae8097bf0bd095279b79885e648d27ed6fb27b63e5b9c15f6d` |
| `datasets/distributor-v1/raw/CD-A03.eml` | `sha256:fd312f561fae4aff1cc1e53a890d8f608fff1ffc4073c1c71952912e3e68325d` |
| `datasets/distributor-v1/raw/CD-A04.whatsapp.json` | `sha256:567254b807aebc363fbd724af84f12c46666fb16b9106b1d57769c9fad1b1e02` |
| `datasets/distributor-v1/raw/CD-A05.eml` | `sha256:c0c0a99db17c8d8e2707772403b5e344e6af2b64a39bc890e68bd7ca70cd85fe` |
| `datasets/distributor-v1/raw/CD-A06.eml` | `sha256:9a7b7d21b02a73dd2e95389da5628005cae6be6157f1a8b195a53c7d7dec2c66` |
| `datasets/distributor-v1/raw/OID-001.eml` | `sha256:ba6157cfb2b60c66954b59edaa208a2e173ac0c00e20758739216f105ee6dd53` |
| `datasets/distributor-v1/raw/OID-002.eml` | `sha256:3981b4014bf72aee0ba54796e4fc9043a655c894d243fd100f85513ce3483a68` |
| `datasets/distributor-v1/raw/OID-003.eml` | `sha256:996df061eab5b4a0f070696c3a26c9d00083e3c296274768ea5edecadc89cb91` |
| `datasets/distributor-v1/raw/OID-004.whatsapp.json` | `sha256:366898c2414ea02f2f606cbcbc0a21cabae2a2b2a27475156572e2845df34279` |
| `datasets/distributor-v1/raw/OID-005.eml` | `sha256:7dd892b464401d3d75a1afc483528566b661e7767c71121805a6d99a221e11d8` |
| `datasets/distributor-v1/raw/OID-006.eml` | `sha256:389c664e49c3b0657f2e3551918c48a2d8969a80be1fe328fa939bcbe0c09c9b` |
| `datasets/distributor-v1/raw/OID-007.eml` | `sha256:cb21d4e0316ee6bba390650ec2e7dfa4566dcf281682fa714fde11f3815e277e` |
| `datasets/distributor-v1/raw/OID-008.eml` | `sha256:9d89f3e5b8623ef26f4cb9cee0643e16dc2f8757b4bf52ea00856650b018147f` |
| `datasets/distributor-v1/raw/OID-009.eml` | `sha256:46bdcb0d9a8ff20c09c23d9a4cb33883db3d66bc6375c27f1733cd9f5dd2efa8` |
| `datasets/distributor-v1/raw/OID-010.eml` | `sha256:eba161f694c23d8ccbb060122a62329190185a87f402ca3ca7fdba1ec93ef61d` |
| `datasets/distributor-v1/raw/OID-011.eml` | `sha256:c191b246227f599e3da9854a1bc1f2ea7d3d9eb7baca35965a4d599cd9a8857f` |
| `datasets/distributor-v1/raw/OID-012.eml` | `sha256:aa34a4ccf651b733e6e58b647da474f4acbdb02f84a6b2975f7e0596320280ce` |
| `datasets/distributor-v1/raw/OID-A01.eml` | `sha256:ba6157cfb2b60c66954b59edaa208a2e173ac0c00e20758739216f105ee6dd53` |
| `datasets/distributor-v1/raw/OID-A02.eml` | `sha256:6bf0afc799947c82863bab75a37752ee4bbd0a86227d5a04ef313457992c4a84` |
| `datasets/distributor-v1/raw/OID-A03.eml` | `sha256:b4a2dc4676811536c35c8673c2fd1ae06c27af9c68b5ac63931db3798a4e1f4b` |
| `datasets/distributor-v1/raw/OID-A04.eml` | `sha256:d33ea1fca2e6491a9c0fc4cd0e8e603eb96dde77e66b66a9cc0c6eafd709d4dd` |
| `datasets/distributor-v1/raw/OID-A05.eml` | `sha256:e29408e35407247a706dcf690c44f905966bca323ce7711f3d73206cc4bcbeaf` |
| `datasets/distributor-v1/raw/OID-A06.eml` | `sha256:f3d4cb549ff54ba87ffb1a560c88e32d503eadf88a7a4c4c791bdd757832b4d5` |
| `datasets/distributor-v1/raw/OID-A07.eml` | `sha256:b68a7724e6bea7a835658cd00725d794b2af6383a2f05d95591fb10fb181914a` |
| `datasets/distributor-v1/raw/OID-X01.eml` | `sha256:4312dca7d9ba27b02da093b7b4975812ad8604eef9916d602b685b00d12a6217` |
| `datasets/generate.py` | `sha256:a13d4fbd60be3acf6ddc014388539a52d9bbadc1bf63fb0f73974e9234a79b2c` |
| `datasets/spec_distributor_v1.py` | `sha256:e2db1dc542ed08293ae8691ba00d57389caa7c4c0e58160e131471d6a06594f1` |
| `doctor.py` | `sha256:63ad3196d76fc45a83b8f9b8b4d9124ea8873d1323e0f854527252b59b91f903` |
| `errors.py` | `sha256:224dcf48f48597dbf3e76ccebf5de3eab38a8afc4c5798954685fd13442a1bd1` |
| `fake_server.py` | `sha256:b26345b16e29820e8abad14ea8064b81b550a2e47b1f7916cb0afe0afad1b2c4` |
| `filters.py` | `sha256:fdfc65034cd6b27ef7c9eaec900f77159098c81d5e136e247b807dce1d8e569a` |
| `http.py` | `sha256:d68dfa9e56efa6779639c62bd32a0329dae242872dc609bd059ed0c035e3c7f1` |
| `models.py` | `sha256:12e0bb6285da59328f48dcab9171cee8dc559711b6710c6ffbc25c149c0785bb` |
| `read.py` | `sha256:bdbc10715073da53bf4cf42a67831a96f9c3db330a37ab3685a836306dbb751c` |
| `resources.py` | `sha256:bbb28fdad6826d3c4d3d6febcfef631fd09af8a3ade1421752b5ca0527d5bb3b` |
| `service.py` | `sha256:410cde848b0ff6866526b0eb9b6174b53e423f3399512ed5b517b7c494f1bb01` |
