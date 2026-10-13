from live import kol_clusters


def test_labels_cover_registry_and_types():
    lab = kol_clusters.labels()
    assert len(lab) > 200
    assert set(lab.values()) <= {'macro_research', 'sell_side', 'onchain', 'traders', 'media', 'zh_community'}


def test_cluster_count_distinct_types():
    lab = kol_clusters.labels()
    by = {}
    for h, c in lab.items():
        by.setdefault(c, h)
    a, b = list(by.items())[:2]
    ms = [{'adapter': 'x:' + a[1]}, {'adapter': 'x:' + a[1]}, {'adapter': 'x:' + b[1]}, {'adapter': 'x:nobody_zz'},
          {'adapter': 'rss'}]
    got = kol_clusters.clusters(ms)
    assert a[0] in got and b[0] in got and 'media' in got and len(got) == len({a[0], b[0], 'media'})


def test_weight_env():
    assert kol_clusters.weight({'FD_KOL_CLUSTER_W': '0'}) == 0.0
    assert kol_clusters.weight({}) == 0.8
