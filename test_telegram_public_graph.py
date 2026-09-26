import unittest

import telegram_public_graph as tpg


SAMPLE_HTML = """
<html>
  <body>
    <div class="tgme_channel_info_header_title"><span>North Cyprus Buyers</span></div>

    <div class="tgme_widget_message_wrap">
      <div class="tgme_widget_message" data-post="ncbuyers/101">
        <a class="tgme_widget_message_author" href="https://t.me/realbuyer">@realbuyer</a>
        <div class="tgme_widget_message_text">
          Куплю 2+1 в Фамагусте. Смотрите также @linked_channel
          <a href="https://t.me/s/another_channel/55">link</a>
        </div>
        <time datetime="2026-09-25T10:00:00+00:00"></time>
      </div>
    </div>

    <div class="tgme_widget_message_wrap">
      <div class="tgme_widget_message" data-post="ncbuyers/102">
        <div class="tgme_widget_message_text">
          Information only
          <a href="https://t.me/share/url?url=x">share</a>
          <a href="https://t.me/joinchat/abcdef">join</a>
        </div>
        <time datetime="2026-09-25T11:00:00+00:00"></time>
      </div>
    </div>
  </body>
</html>
"""


class TelegramPublicGraphTests(unittest.TestCase):
    def test_extracts_public_usernames_and_ignores_reserved_paths(self):
        text = (
            "https://t.me/s/alpha_channel/42 @BetaChannel "
            "https://t.me/share/url?url=x https://t.me/joinchat/abcdef"
        )
        found = {x.casefold() for x in tpg.extract_public_usernames(text)}
        self.assertIn("alpha_channel", found)
        self.assertIn("betachannel", found)
        self.assertNotIn("share", found)
        self.assertNotIn("joinchat", found)

    def test_parses_preview_messages_and_graph_references(self):
        page = tpg.parse_public_preview(SAMPLE_HTML, "ncbuyers")
        self.assertEqual(page["username"], "ncbuyers")
        self.assertEqual(page["title"], "North Cyprus Buyers")
        self.assertEqual(len(page["messages"]), 2)

        first = page["messages"][0]
        self.assertEqual(first["message_id"], 101)
        self.assertEqual(first["author"], "@realbuyer")
        self.assertEqual(first["url"], "https://t.me/ncbuyers/101")
        refs = {x.casefold() for x in first["references"]}
        self.assertIn("linked_channel", refs)
        self.assertIn("another_channel", refs)

        all_refs = {x.casefold() for x in page["references"]}
        self.assertNotIn("realbuyer", all_refs)
        self.assertIn("linked_channel", all_refs)
        self.assertIn("another_channel", all_refs)
        self.assertNotIn("share", all_refs)
        self.assertNotIn("joinchat", all_refs)

    def test_rejects_cross_channel_data_post(self):
        html = """
        <div class="tgme_widget_message_wrap">
          <div class="tgme_widget_message" data-post="otherchannel/5">
            <div class="tgme_widget_message_text">hello</div>
          </div>
        </div>
        """
        page = tpg.parse_public_preview(html, "expectedchannel")
        self.assertEqual(page["messages"], [])

    def test_datetime_parser_handles_iso_timezone(self):
        dt = tpg.parse_datetime("2026-09-25T10:00:00+00:00")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.year, 2026)
        self.assertIsNone(tpg.parse_datetime("not-a-date"))


if __name__ == "__main__":
    unittest.main()
