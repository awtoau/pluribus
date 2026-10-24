module top (
    input [0:0] clk,
    input [0:0] go,
    input [0:0] abort,
    output reg [0:0] last,
    output reg [0:0] busy
);
  localparam S0 = 8'd1;
  localparam S1 = 8'd2;
  localparam S2 = 8'd4;
  localparam S3 = 8'd8;
  localparam S4 = 8'd16;
  localparam S5 = 8'd32;
  localparam S6 = 8'd64;
  localparam S7 = 8'd128;
  reg [7:0] st;
  reg [7:0] ns;
  always @* begin
    ns = st;
    case (st)
      S0: if (abort) ns = S0; else if (go) ns = S1;
      S1: if (abort) ns = S0; else if (go) ns = S2;
      S2: if (abort) ns = S0; else if (go) ns = S3;
      S3: if (abort) ns = S0; else if (go) ns = S4;
      S4: if (abort) ns = S0; else if (go) ns = S5;
      S5: if (abort) ns = S0; else if (go) ns = S6;
      S6: if (abort) ns = S0; else if (go) ns = S7;
      S7: if (abort) ns = S0; else if (go) ns = S0;
      default: ns = S0;
    endcase
  end
  always @(posedge clk) begin
    st <= ns;
    last <= (ns == S7);
    busy <= (ns != S0);
  end
endmodule
