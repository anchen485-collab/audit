from app.DataCleaning import WebsiteTextCleaner


def test_website_text_cleaner_keeps_business_evidence_and_drops_boilerplate():
    cleaner = WebsiteTextCleaner()

    cleaned = cleaner.clean(
        """
        首页 导航 联系我们 在线留言 版权所有 ICP备案号
        公司简介 我们专注水稻、小麦等谷物种植、加工和销售。
        产品服务 香甜软糯，提供大米加工礼盒和休闲食品。
        业务领域 提供粮食仓储、稻米加工和供应链服务。
        电话：400-123-4567 邮箱：hello@example.com
        公司简介 我们专注水稻、小麦等谷物种植、加工和销售。
        """
    )

    assert "水稻" in cleaned.text
    assert "粮食仓储" in cleaned.text
    assert "香甜软糯" not in cleaned.text
    assert "ICP备案号" not in cleaned.text
    assert "hello@example.com" not in cleaned.text
    assert cleaned.kept_fragment_count >= 2
    assert cleaned.dropped_fragment_count >= 1


def test_website_text_cleaner_only_keeps_allowed_sections():
    cleaner = WebsiteTextCleaner()

    cleaned = cleaner.clean(
        """
        产品中心 进口玉芒 香甜软润，蓝莓整果鲜制。
        公司简介 企业是集种植、研发、生产、销售为一体的食品企业。
        经典案例 为大型农业基地提供稻米加工项目服务。
        新闻资讯 荣获行业大奖，品牌代言活动启动。
        使命 我们致力于提供优秀产品和服务。
        业务领域 覆盖谷物种植、粮食加工、仓储和出口贸易。
        """
    )

    assert "食品企业" in cleaned.text
    assert "稻米加工项目" in cleaned.text
    assert "谷物种植" in cleaned.text
    assert "进口玉芒" not in cleaned.text
    assert "品牌代言" not in cleaned.text
    assert "优秀产品和服务" not in cleaned.text


def test_website_text_cleaner_keeps_business_signal_without_known_section_heading():
    cleaner = WebsiteTextCleaner()

    cleaned = cleaner.clean(
        """
        首页 产品中心 香甜软糯 口感浓郁。
        主营业务包括动物疫苗研发、生产和销售，服务家禽养殖企业。
        核心能力覆盖兽用生物制品制造、技术服务和供应链支持。
        新闻资讯 荣获行业大奖。
        """
    )

    assert "动物疫苗研发" in cleaned.text
    assert "兽用生物制品制造" in cleaned.text
    assert "香甜软糯" not in cleaned.text
    assert "行业大奖" not in cleaned.text
