// Moore FSM: detects the serial sequence 1011 (overlapping).
module fsm_seqdet(input clk, input rst, input din, output reg hit, output [2:0] st);
  localparam S0 = 3'd0, S1 = 3'd1, S10 = 3'd2, S101 = 3'd3, S1011 = 3'd4;
  reg [2:0] s;
  always @(posedge clk)
    if (rst) s <= S0;
    else case (s)
      S0:    s <= din ? S1 : S0;
      S1:    s <= din ? S1 : S10;
      S10:   s <= din ? S101 : S0;
      S101:  s <= din ? S1011 : S10;
      S1011: s <= din ? S1 : S10;
      default: s <= S0;
    endcase
  always @(posedge clk) hit <= (s == S1011);
  assign st = s;
endmodule
